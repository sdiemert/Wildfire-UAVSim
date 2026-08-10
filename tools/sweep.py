"""Runs parameter sweeps over the simulator and reports how hard each configuration is.

`headless.py` already does everything expensive about running a batch: parallel workers, per-run seed
derivation, `config.validate()` on the overrides, failure isolation, and a JSON record of every run. What
it does not do is enumerate a set of configurations, record *which* configuration produced a given run --
its JSON carries the metrics but not the `--set` values or the policy -- or say anything statistical about
the results. That is what this module adds, and it is deliberately all it adds.

The question it exists to answer is "how difficult is this configuration", measured as the share of runs a
policy wins, a run being won by finishing with the home base still standing. Difficulty is not a monotone
function of any single setting: several of them are cliffs, where one integer step takes a scenario from
comfortable to unwinnable. So `scan` maps a region and `calibrate` bisects within one, and both report a
Wilson score interval rather than a bare proportion, because at a win rate near 0.1 the normal
approximation is wide of the mark and can produce a lower bound below zero.

Each arm runs in its own `headless.py` subprocess rather than by calling `sim.cli.main.main()` in this
one. `apply_overrides()` and `seed_simulation()` mutate the global `config` module, so arms sharing a
process leak settings into one another unless every arm happens to set every key any other arm sets. The
subprocess costs about a fifth of a second of interpreter startup, amortised over `--runs`, and removes
that whole class of mistake.

Every arm of one sweep shares a seed block, so the same run index means the same fire in every arm and the
comparison between them is paired. The block itself is drawn fresh per sweep unless `--seed` says
otherwise, and reported and recorded when it is -- sharing one block *across* sweeps is not pairing, it is
fitting everything the tool has ever measured to one set of fires. That risk remains within a sweep: a
value tuned by `calibrate` is fitted to the fires it was bisected on, so confirm it on a disjoint block
before believing it.

Usage:
    python3 tools/sweep.py scan --policy firefighter --runs 100 \\
        --base WIDTH=100 --base HEIGHT=100 --base BATCH_SIZE=100 \\
        --axis BHP=2,3,4,5 --axis FIRE_SPREAD_SPEED=1,2 --out experiments/coarse

    python3 tools/sweep.py calibrate --policy firefighter --knob EXTINGUISH_SCALE \\
        --low 0.6 --high 1.0 --target 0.10 --runs 400 --out experiments/calibrate

    # the reported seed replays a sweep exactly, and is the way to re-measure on a disjoint block
    python3 tools/sweep.py scan --seed 500000 ...
"""

# python libraries

import argparse
import csv
import json
import math
import subprocess
import sys

from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

# the repository root, so that this runs as a script from anywhere and can still import the simulator
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# own python modules

from sim.cli.overrides import draw_base_seed, parse_override


HEADLESS = REPO_ROOT / "headless.py"


# --- derived axes -----------------------------------------------------------

# Some things worth sweeping are not a single constant. Water strength is the one that matters here: a
# drop's chance of putting a cell out falls linearly from WATER_EXTINGUISH_PROB_CENTRE to
# WATER_EXTINGUISH_PROB_EDGE, and sweeping the two independently would spend most of the arms on
# combinations nobody wants -- including the ones where the edge is stronger than the centre. Scaling both
# by one number keeps the shape of the falloff and gives a single continuous dial to bisect on.
#
# Add an entry here rather than teaching the caller to write coupled --set values; the point is that the
# swept quantity appears in the results under one name.
DERIVED = {
    "EXTINGUISH_SCALE": lambda scale: {"WATER_EXTINGUISH_PROB_CENTRE": round(0.95 * scale, 6),
                                       "WATER_EXTINGUISH_PROB_EDGE": round(0.60 * scale, 6)},
    # sweeping WIDTH and HEIGHT as two axes spends three quarters of the arms on rectangles nobody asked
    # for, and the interesting quantity is the size of the map rather than its shape
    "GRID": lambda size: {"WIDTH": int(size), "HEIGHT": int(size)},
}


def expand(name, value):
    """Return the config overrides one axis value stands for.

    A plain constant stands for itself; a derived name expands into the several constants it controls.
    """
    if name in DERIVED:
        return DERIVED[name](value)
    return {name: value}


# --- statistics -------------------------------------------------------------


def wilson(successes, trials, z=1.96):
    """The Wilson score interval for a proportion, as (low, high).

    Preferred over the normal approximation because the win rates being measured here sit near 0.1 with a
    few hundred trials, which is exactly where the normal interval misbehaves -- it is symmetric about a
    proportion that has no room to be symmetric, and its lower bound goes negative. Wilson stays inside
    [0, 1] and is not fooled by a run of zero wins.
    """
    if trials <= 0:
        return (0.0, 1.0)

    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (proportion + z * z / (2 * trials)) / denominator
    spread = z * math.sqrt(proportion * (1 - proportion) / trials + z * z / (4 * trials * trials))
    spread /= denominator
    return (max(0.0, centre - spread), min(1.0, centre + spread))


# --- one arm ----------------------------------------------------------------


@dataclass
class Arm:
    """One configuration to measure: the swept parameters, and the config overrides they expand into."""

    params: dict = field(default_factory=dict)      # what was swept, under the names it was swept by
    settings: dict = field(default_factory=dict)    # what config.py actually gets told

    @property
    def label(self):
        return " ".join(f"{name}={value}" for name, value in self.params.items()) or "(base)"

    @property
    def slug(self):
        """A filename for this arm's JSON, unique because the parameter values are."""
        parts = [f"{name}-{value}" for name, value in self.params.items()] or ["base"]
        return "_".join(str(part).replace("/", "-").replace(" ", "") for part in parts)


def build_arms(base, axes):
    """The cartesian product of the axes, each arm carrying the base settings underneath its own.

    An axis value overrides a base setting of the same name rather than conflicting with it, so a scan can
    pin a knob in --base and still vary it on one axis.
    """
    names = list(axes)
    arms = []
    for combination in product(*(axes[name] for name in names)):
        params = dict(zip(names, combination))
        settings = dict(base)
        for name, value in params.items():
            settings.update(expand(name, value))
        arms.append(Arm(params=params, settings=settings))
    return arms


def format_value(value):
    """Render a value for `headless.py --set NAME=VALUE`.

    `--set` evaluates the text as a Python literal and falls back to the raw string, so a string is passed
    bare (WIND_DIRECTION=south) and everything else goes through repr(), which round-trips ints, floats,
    booleans, None and tuples.
    """
    return value if isinstance(value, str) else repr(value)


def arm_command(arm, options, output_path):
    """The `headless.py` invocation for one arm."""
    command = [sys.executable, str(HEADLESS),
               "--runs", str(options.runs),
               "--workers", str(options.workers),
               "--policy", options.policy,
               "--managing", options.managing,
               "--log-every", "0",
               "--log-level", options.log_level,
               "--output", str(output_path)]
    if options.seed is not None:
        command += ["--seed", str(options.seed)]
    for name, value in arm.settings.items():
        command += ["--set", f"{name}={format_value(value)}"]
    return command


def run_arm(arm, options, out_dir):
    """Run one arm and return its per-run result dictionaries, each tagged with the arm it came from.

    A failing subprocess is raised rather than skipped. `headless.py` already survives a run that throws --
    it records the error in the result -- so a non-zero exit means the *configuration* was rejected, and
    quietly dropping the arm would leave a hole in the surface that nobody would notice.
    """
    output_path = out_dir / f"{arm.slug}.json"
    command = arm_command(arm, options, output_path)

    completed = subprocess.run(command, capture_output=True, text=True, cwd=REPO_ROOT)
    if completed.returncode != 0:
        raise RuntimeError(f"arm {arm.label} failed (exit {completed.returncode}):\n"
                           f"{completed.stderr.strip()[-2000:]}")

    # The arm's identity is written twice on purpose: once to put those columns first, and once after the
    # result so that it wins any collision. A RunResult field and a swept parameter can share a name --
    # `managing` is both a boolean in the result and the thing this tool was told to run -- and the
    # collision costs the identity of the row, which is the one column the join exists to provide.
    identity = {"arm": arm.label, "policy": options.policy, "managing_asked": options.managing,
                **arm.params}
    return [{**identity, **result, **identity} for result in json.loads(output_path.read_text())]


def summarise(rows):
    """Win rate and its interval for one arm's runs.

    A run with `outcome` of N/A -- firefighting switched off, so there is no base to lose -- has no notion
    of winning, and is counted in `n` but excluded from the rate, which is reported as None. Silently
    treating those as losses is how a sweep with a mis-set ACTIVATE_FIREFIGHTING would produce a plausible
    looking 0%.
    """
    decided = [row for row in rows if row.get("outcome") in ("WON", "LOST")]
    wins = sum(1 for row in decided if row["outcome"] == "WON")
    errors = sum(1 for row in rows if row.get("error"))

    if not decided:
        return {"n": len(rows), "decided": 0, "wins": 0, "rate": None, "low": None, "high": None,
                "errors": errors}

    low, high = wilson(wins, len(decided))
    return {"n": len(rows), "decided": len(decided), "wins": wins, "rate": wins / len(decided),
            "low": low, "high": high, "errors": errors}


# --- output -----------------------------------------------------------------


def write_csv(path, rows):
    """One row per run, long format, with the swept parameters joined on.

    The columns are the union over every row, because a result carries different fields depending on which
    extensions were switched on. Sorting them would scatter the swept parameters through the metrics, so
    the order of first appearance is kept instead: arm, parameters, then the run's own fields.
    """
    columns = []
    for row in rows:
        for name in row:
            if name not in columns:
                columns.append(name)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return columns


def format_table(measured):
    """The win-rate table, ordered hardest first, as a list of lines."""
    lines = [f"{'arm':<44} {'won':>9}  {'rate':>7}  {'95% Wilson':>16}"]
    lines.append("-" * 82)
    for arm, stats in sorted(measured, key=lambda pair: (pair[1]["rate"] is None, pair[1]["rate"] or 0.0)):
        if stats["rate"] is None:
            lines.append(f"{arm.label:<44} {'--':>9}  {'n/a':>7}  {'no decided runs':>16}")
            continue
        won = f"{stats['wins']}/{stats['decided']}"
        interval = f"{stats['low']:.1%} - {stats['high']:.1%}"
        note = f"  ({stats['errors']} errored)" if stats["errors"] else ""
        lines.append(f"{arm.label:<44} {won:>9}  {stats['rate']:>6.1%}  {interval:>16}{note}")
    return lines


# --- scan -------------------------------------------------------------------


def scan(options, report=print):
    """Measure every arm in the cartesian product of the axes, write the CSV, print the table."""
    arms = build_arms(options.base, options.axes)
    out_dir = Path(options.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    report(f"{len(arms)} arm(s) x {options.runs} run(s), policy={options.policy} "
           f"managing={options.managing} seed={options.seed}")

    rows, measured = [], []
    for index, arm in enumerate(arms, start=1):
        arm_rows = run_arm(arm, options, out_dir)
        stats = summarise(arm_rows)
        rows += arm_rows
        measured.append((arm, stats))
        rate = "n/a" if stats["rate"] is None else f"{stats['rate']:.1%}"
        report(f"  [{index}/{len(arms)}] {arm.label:<44} {rate:>7}")

    csv_path = out_dir / "runs.csv"
    write_csv(csv_path, rows)

    report("")
    for line in format_table(measured):
        report(line)
    report("")
    report(f"wrote {csv_path}")
    return measured


# --- calibrate --------------------------------------------------------------


def calibrate(options, report=print):
    """Bisect one knob for the value that puts the win rate on the target.

    The direction is measured rather than assumed: the two ends of the bracket are probed first, and which
    of them wins more decides which way the knob runs. That is worth the two extra probes, because the
    knobs here do not agree on a direction -- a bigger grid makes the scenario easier, a bigger BHP makes
    it easier, a smaller extinguish probability makes it harder -- and a bisection that assumes the wrong
    one converges confidently on an endpoint.

    Monotonicity between the ends is still assumed, which bisection cannot check. The probe sequence is
    reported in full so that a non-monotone knob shows up as a rate that moves the wrong way.
    """
    out_dir = Path(options.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, probes = [], []

    def probe(value):
        arm = Arm(params={options.knob: round(value, 6)},
                  settings={**options.base, **expand(options.knob, round(value, 6))})
        arm_rows = run_arm(arm, options, out_dir)
        stats = summarise(arm_rows)
        if stats["rate"] is None:
            raise RuntimeError(f"{arm.label} produced no decided runs -- is ACTIVATE_FIREFIGHTING on?")
        rows.extend(arm_rows)
        probes.append((value, stats))
        report(f"  {options.knob}={value:<12.6g} {stats['wins']}/{stats['decided']} "
               f"= {stats['rate']:.1%}  [{stats['low']:.1%} - {stats['high']:.1%}]")
        return stats

    report(f"target {options.target:.1%} on {options.knob} in [{options.low}, {options.high}], "
           f"{options.runs} run(s) per probe, policy={options.policy} seed={options.seed}")

    low, high = options.low, options.high
    low_stats, high_stats = probe(low), probe(high)

    # which end is which, and whether the target is between them at all
    ascending = high_stats["rate"] >= low_stats["rate"]
    lowest, highest = sorted([low_stats["rate"], high_stats["rate"]])
    if not lowest <= options.target <= highest:
        report(f"\ntarget {options.target:.1%} is outside the bracket "
               f"({lowest:.1%} - {highest:.1%}); widen it or pick another knob")
        write_csv(out_dir / "runs.csv", rows)
        return None

    best = min([(low, low_stats), (high, high_stats)],
               key=lambda pair: abs(pair[1]["rate"] - options.target))

    for _ in range(options.max_probes):
        if high - low <= options.tolerance:
            break
        middle = (low + high) / 2.0
        stats = probe(middle)

        if abs(stats["rate"] - options.target) < abs(best[1]["rate"] - options.target):
            best = (middle, stats)

        # a probe whose interval already covers the target is as close as this sample size can resolve;
        # halving again would only be reading noise
        if stats["low"] <= options.target <= stats["high"]:
            best = (middle, stats)
            report(f"  target inside the interval at {options.knob}={middle:.6g}; stopping")
            break

        if (stats["rate"] < options.target) == ascending:
            low = middle
        else:
            high = middle

    value, stats = best
    report("")
    report(f"{options.knob} = {value:.6g}  ->  {stats['rate']:.1%} "
           f"[{stats['low']:.1%} - {stats['high']:.1%}] over {stats['decided']} run(s)")
    for name, expanded in expand(options.knob, round(value, 6)).items():
        report(f"    {name} = {expanded}")
    report("")
    report("confirm this on a seed block it was not fitted to before adopting it.")

    csv_path = out_dir / "runs.csv"
    write_csv(csv_path, rows)
    report(f"wrote {csv_path}")
    return value, stats


# --- command line -----------------------------------------------------------


def parse_axis(text):
    """Parse an axis of the form NAME=v1,v2,v3 into (name, [values]).

    Values are read the way `headless.py --set` reads them, so 1 is an int, 0.5 a float, True a boolean and
    anything unparseable a string. A value containing a comma cannot be expressed -- add a derived axis
    instead of teaching this to quote.
    """
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"expected NAME=v1,v2,..., got {text!r}")
    name, _, raw = text.partition("=")
    values = [parse_override(f"{name}={piece.strip()}")[1] for piece in raw.split(",") if piece.strip()]
    if not values:
        raise argparse.ArgumentTypeError(f"axis {name.strip()!r} has no values")
    return name.strip(), values


def add_common(parser):
    parser.add_argument("--policy", default="firefighter", help="the policy under test")
    parser.add_argument("--managing", default="none",
                        help="managing system for every arm; 'none' measures the bare policy")
    parser.add_argument("--runs", type=int, default=100, help="runs per arm")
    parser.add_argument("--workers", type=int, default=8, help="parallel workers within an arm")
    parser.add_argument("--seed", type=int, default=None,
                        help="base seed, shared by every arm so the arms see the same fires. Without "
                             "it a block is drawn from OS entropy and reported, so two sweeps do not "
                             "silently reuse one set of fires")
    # deliberately no --steps. It is an alias for BATCH_SIZE in headless.py, so accepting it here would
    # give a sweep two names for one axis and let an arm set the run length twice. Sweep BATCH_SIZE
    # instead -- it is the constant the model itself stops on, and one of the strongest difficulty dials
    # in the configuration. The two were once separate, and a sweep over --steps 120, 150 and 200 came
    # back with three identical win rates: above BATCH_SIZE the flag did nothing, which reads as run
    # length not mattering. That is why there is one name for it here.
    parser.add_argument("--base", metavar="NAME=VALUE", action="append", default=[],
                        help="a setting held fixed across every arm; repeatable")
    parser.add_argument("--out", default="experiments/sweep", help="directory for the JSON and the CSV")
    parser.add_argument("--log-level", default="ERROR", help="log level passed to headless.py")


def build_parser():
    parser = argparse.ArgumentParser(description="parameter sweeps over the wildfire simulator")
    commands = parser.add_subparsers(dest="command", required=True)

    scan_parser = commands.add_parser("scan", help="measure the cartesian product of some axes")
    add_common(scan_parser)
    scan_parser.add_argument("--axis", metavar="NAME=v1,v2,...", action="append", default=[],
                             required=True, help="a swept parameter and its values; repeatable")

    calibrate_parser = commands.add_parser("calibrate", help="bisect one knob for a target win rate")
    add_common(calibrate_parser)
    calibrate_parser.add_argument("--knob", required=True, help="the constant, or derived axis, to bisect")
    calibrate_parser.add_argument("--low", type=float, required=True)
    calibrate_parser.add_argument("--high", type=float, required=True)
    calibrate_parser.add_argument("--target", type=float, default=0.10, help="win rate to aim for")
    calibrate_parser.add_argument("--tolerance", type=float, default=0.01,
                                  help="stop once the bracket is this narrow")
    calibrate_parser.add_argument("--max-probes", type=int, default=10)

    return parser


def main(argv=None):
    options = build_parser().parse_args(argv)
    options.base = dict(parse_override(text) for text in options.base)

    # Resolved once, here, rather than per arm: every arm of one sweep has to receive the same --seed for
    # the comparison between them to be paired. Resolving it also means an unseeded sweep gets a fresh
    # block each time it is run. The default used to be the constant 1000, so every sweep anybody ran
    # without thinking about it was fitted to one set of fires -- and repeating a sweep returned the same
    # numbers, which reads as a stable measurement rather than as the same measurement.
    if options.seed is None:
        options.seed = draw_base_seed()

    try:
        if options.command == "scan":
            options.axes = dict(parse_axis(text) for text in options.axis)
            scan(options)
        else:
            calibrate(options)
    except RuntimeError as problem:
        print(problem, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
