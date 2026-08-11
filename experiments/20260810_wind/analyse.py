#!/usr/bin/env python3
"""Turns the wind experiment's direction sweeps into the numbers in the report.

Reads the per-arm JSON under runs/ and produces

  * arms.csv      one row per arm: the wind it was run under, the loss rate, its 95% Wilson interval, and
                  what the runs that were lost looked like. This is the table the report is built from.
  * summary.json  the same, plus the four consistency checks below.

Two of the five sweeps in run.sh have data: runs/cardinal/ and runs/diagonal/. The others were never
run, and runs/extent/ would have no loss rate to summarise in any case -- extent.py reads that one.

The checks matter more here than in the baseline. The baseline had one arm and could be wrong in only one
way; this has 73 arms across a surface that turns out to be flat over most of its range, and a flat
surface is exactly what a wind setting that silently failed to apply would also produce. So:

  1. Pairing. The ignition cell is drawn before the wind is built, so a seed has to name the same fire in
     every arm of the two direction sweeps. If it does not, the differences between directions are
     partly differences between fires.
  2. MU = 0. Zero wind strength leaves every weight in the kernel untouched, so the four directions at
     MU = 0 have to agree run for run -- not merely in rate -- and have to reproduce the no-wind baseline's
     100% loss. Four identical arms are the cost of being able to say the wind knob is wired up.
  3. The MU = 1 geometry. At full strength the three downwind offsets are certain and every other weight is
     zero, so the fire is a straight line: it is lost if and only if the ignition cell lies on the two-cell
     strip through the base and upwind of it. That is a prediction about *which runs*, not just how many,
     and it is checked run by run.
  4. The baseline. MU = 0 is the no-wind baseline expressed through the wind code, on a seed block the
     baseline never touched, and has to reproduce its 100% loss.

The Wilson interval is imported from tools/sweep.py, as in experiments/20260810_baseline/analyse.py, so
the three cannot disagree about what a 95% interval is.

Run from the repository root:  python3 experiments/20260810_wind/analyse.py
"""

# python libraries

import csv
import json
import re
import pathlib
import statistics
import sys

# own python modules

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.sweep import wilson

HERE = pathlib.Path(__file__).resolve().parent

# The base footprint on a 100x100 grid with BASE_POSITION = None: anchored at (HEIGHT/4, WIDTH/4) and
# covering BASE_SIZE from there. Positions are (x, y) with x over HEIGHT and y over WIDTH, which is the
# order model.resolve_fire_start_position() draws them in and sim/cli/runner.py records.
BASE_X = (25, 26)
BASE_Y = (25, 26)

# Which way each wind direction actually pushes fire. environment.is_on_wind_direction(s, s') asks whether
# the neighbour s' pushes fire into s, so 'south' -- s[1] < s'[1] -- ignites cells with a *smaller* y than
# the cell already burning, and the front therefore travels down the y axis. The names are the simulator's
# and are not worth arguing with; these four vectors are what they mean.
HEADING = {"north": (0, +1), "south": (0, -1), "east": (+1, 0), "west": (-1, 0)}


# --- statistics -------------------------------------------------------------


# loss rate and its 95% Wilson interval over a list of run records, as percentages
def loss_rate(records):
    trials = len(records)
    losses = sum(1 for record in records if record["outcome"] == "LOST")
    if trials == 0:
        return {"n": 0, "lost": 0, "rate": None, "low": None, "high": None}
    low, high = wilson(losses, trials)
    return {"n": trials, "lost": losses, "rate": 100.0 * losses / trials,
            "low": 100.0 * low, "high": 100.0 * high}


# Whether a straight line fire lit at 'start' reaches the base under this direction at MU = 1. The front
# runs along one axis only, so the ignition has to share the other coordinate with the base footprint and
# lie on the upwind side of it.
def reaches_base_in_a_line(direction, start):
    dx, dy = HEADING[direction]
    x, y = start
    if dx:
        return y in BASE_Y and ((x < min(BASE_X)) if dx > 0 else (x > max(BASE_X)))
    return x in BASE_X and ((y < min(BASE_Y)) if dy > 0 else (y > max(BASE_Y)))


# Chebyshev distance from a cell to the nearest cell of the base footprint, as in the baseline's analysis.
def distance_to_base(start):
    return min(max(abs(start[0] - x), abs(start[1] - y)) for x in BASE_X for y in BASE_Y)


# Reaching the base and destroying it are different things, and at MU = 1 the difference is visible. A cell
# burns for a single fire update and then goes out, so the fire is a wave one cell deep rather than a
# growing burning region, and the base takes damage only on the steps the wave is standing on it -- BHP of
# them, four here. A line fire lit right beside the base never gives it those four: the wave ignites
# everything within three cells along the axis in its first update, which clears the two-deep footprint in
# one leap and leaves it burning for two or three steps rather than four.
#
# So the prediction is made only for ignitions further than that first leap. Inside it, the outcome turns
# on which of the footprint's cells the leap happens to cover, and this rule says nothing.
FIRST_LEAP = 3


# --- reading ----------------------------------------------------------------


# One sweep's arms, read from the per-arm JSON that headless.py writes rather than from the merged
# runs.csv that tools/sweep.py writes at the end of a scan. The distinction matters: a scan that was
# interrupted leaves every arm it finished on disk but no CSV at all, and those arms are perfectly good
# measurements. The arm's identity comes from the filename, which is where sweep.py puts it --
# 'FIRST_DIR-north_SECOND_DIR-east_MU-0.9.json' names the axes and their values in order.
def read_arms(directory, axes, discarded):
    if not directory.exists():
        return {}

    # The slug cannot simply be split on '_': half the axis names contain one (WIND_DIRECTION, FIRST_DIR).
    # sweep.py joins the axes in the order they were declared, so match against that order instead.
    pattern = re.compile("^" + "_".join(f"{re.escape(axis)}-(.+?)" for axis in axes) + "$")

    arms = {}
    for path in sorted(directory.glob("*.json")):
        found = pattern.match(path.stem)
        if not found:
            raise SystemExit(f"{path.name} does not name the axes {axes} in that order")
        values = dict(zip(axes, found.groups()))

        runs = json.loads(path.read_text())

        # A run that raised is not a measurement, and counting it as a win or a loss is how an experiment
        # reports a bug as a result. Dropping just the failed runs would be as bad: the arm that was
        # running when this sweep was interrupted has most of a batch on disk, and keeping the survivors
        # would quietly report a rate over whichever runs happened to finish first. So the whole arm goes,
        # and says so.
        failed = [run for run in runs if run.get("error")]
        if failed:
            discarded.append({"arm": path.stem, "runs": len(runs), "errored": len(failed),
                              "first_error": failed[0]["error"]})
            continue

        records = []
        for run in runs:
            if run["outcome"] not in ("WON", "LOST"):
                raise SystemExit(f"arm {path.stem!r} has a run with outcome {run['outcome']!r}: the "
                                 "sweep was run without a home base to lose")
            records.append({
                "seed": int(run["seed"]),
                "outcome": run["outcome"],
                "steps_completed": int(run["steps_completed"]),
                "start": tuple(run["fire_start_pos"]),
                "burning_cells_final": int(run["burning_cells_final"]),
                "burned_out_cells_final": int(run["burned_out_cells_final"]),
            })

        if len({record["seed"] for record in records}) != len(records):
            raise SystemExit(f"arm {path.stem} repeats a seed: its runs are not independent")
        arms[tuple(values[axis] for axis in axes)] = records

    return arms


# --- the checks -------------------------------------------------------------


# Every arm of these two sweeps shares one seed block, so a seed has to name one fire throughout both.
# It does regardless of the wind, and for a reason worth stating: WildFireModel.reset() draws the ignition
# cell at model.py:88 and only builds the FireSpread at model.py:109, so the one draw a composed wind takes
# from SYSTEM_RANDOM to seed its own generator lands *after* the cell has been chosen. The wind therefore
# changes how a fire spreads without changing where it starts, which is what makes 80 arms comparable.
#
# Returns the number of seeds checked, and raises if two arms disagree about where a seed's fire started.
def check_pairing(sweeps):
    fires = {}
    for what, arms in sweeps.items():
        for key, records in arms.items():
            for record in records:
                seen = fires.setdefault(record["seed"], (what, key, record["start"]))
                if seen[2] != record["start"]:
                    raise SystemExit(
                        f"seed {record['seed']} lit at {seen[2]} in {seen[0]} arm {seen[1]} and at "
                        f"{record['start']} in {what} arm {key} -- the arms are not paired on the fire")
    return len(fires)


# At MU = 0 the wind multiplies every weight by one, so the direction cannot matter. Anything less than
# outcome-for-outcome agreement across the four directions means a direction is reaching the kernel by some
# path that MU does not gate, and every difference reported at higher MU would be suspect.
def check_zero_wind_is_directionless(arms, composed=None):
    zero = {key: records for key, records in arms.items() if float(key[1]) == 0.0}
    outcomes = {}
    for key, records in zero.items():
        outcomes[key] = {record["seed"]: record["outcome"] for record in records}

    keys = sorted(outcomes)
    first = outcomes[keys[0]]
    for key in keys[1:]:
        differing = [seed for seed, outcome in first.items() if outcomes[key].get(seed) != outcome]
        if differing:
            raise SystemExit(f"at MU = 0, arms {keys[0]} and {key} disagree on {len(differing)} runs; "
                             "wind direction is affecting a run it cannot affect")
    result = {"arms": len(keys), "runs_each": len(first),
              **loss_rate([record for records in zero.values() for record in records])}

    # The same question of the composed path, reported rather than required. A composed wind normally takes
    # a draw from SYSTEM_RANDOM to seed its own generator, which would shift every later draw and give it a
    # different fire; at MU = 0 the two kernels it mixes are identical, so there is nothing to draw for and
    # it should fall exactly onto the fixed arms. That is a claim about an optimisation in fire_spread.py
    # rather than about the wind, so a mismatch here is worth reporting and not worth refusing to publish.
    if composed is not None:
        matching = 0
        total = 0
        for key, records in composed.items():
            if float(key[-1]) != 0.0:
                continue
            for record in records:
                total += 1
                matching += first.get(record["seed"]) == record["outcome"]
        result["composed_arms_agreeing"] = {"runs": total, "identical": matching}

    return result


# The MU = 1 prediction, run by run rather than in aggregate. Two rates agreeing is weak evidence when both
# are near a boundary; the same *runs* being lost is not.
def check_line_fire_prediction(arms):
    checked = []
    for key, records in sorted(arms.items()):
        direction, mu = key[0], float(key[1])
        if mu != 1.0:
            continue

        on_line = [r for r in records if reaches_base_in_a_line(direction, r["start"])]
        far = [r for r in on_line if distance_to_base(r["start"]) > FIRST_LEAP]
        near = [r for r in on_line if distance_to_base(r["start"]) <= FIRST_LEAP]

        predicted = {record["seed"] for record in far}
        actual = {record["seed"] for record in records if record["outcome"] == "LOST"}
        # a run the rule does not speak for cannot count against it either way
        actual_far = actual - {record["seed"] for record in near}

        # the length of the strip upwind of the base, which is what makes the four directions differ
        dx, dy = HEADING[direction]
        span = (min(BASE_X) if dx > 0 else 99 - max(BASE_X)) if dx else (min(BASE_Y) if dy > 0 else 99 - max(BASE_Y))
        checked.append({
            "direction": direction,
            "upwind_strip_cells": 2 * span,
            "expected_rate": 100.0 * 2 * span / (100 * 100 - 4),
            "predicted_lost": len(predicted),
            "actual_lost": len(actual_far),
            "predicted_not_lost": sorted(predicted - actual_far),
            "lost_not_predicted": sorted(actual_far - predicted),
            "within_first_leap": {"n": len(near),
                                  "lost": sum(1 for r in near if r["outcome"] == "LOST")},
            **loss_rate(records),
        })
    return checked


# The comparison the whole experiment exists to make: every arm here against the no-wind baseline of
# experiments/20260810_baseline/, which lost 5000 of 5000 runs.
#
# The two cannot be paired. The baseline drew its fires from seeds 1 000 000 upwards and this experiment
# draws from 3 000 000, deliberately, because reusing a block across experiments is not pairing -- it is
# fitting every measurement ever taken to one set of fires. So the comparison is between independent
# samples, and the honest internal comparator is the MU = 0 arms: the same code with the wind switched on
# and turned all the way down, on this experiment's own fires. If those do not reproduce the baseline,
# nothing else here can be read against it.
BASELINE = {"n": 5000, "lost": 5000, "rate": 100.0, "low": 99.92322698624194, "high": 100.0}


def compare_with_baseline(cardinal):
    # every arm that is statistically indistinguishable from the baseline, in the sense that the
    # baseline's rate lies inside the arm's interval
    indistinguishable = []
    for (direction, mu), records in sorted(cardinal.items(), key=lambda kv: (kv[0][0], float(kv[0][1]))):
        stats = loss_rate(records)
        if stats["low"] <= BASELINE["rate"] <= stats["high"]:
            indistinguishable.append({"direction": direction, "mu": float(mu), **stats})

    zero = [records for (direction, mu), records in cardinal.items() if float(mu) == 0.0]
    return {
        "baseline": BASELINE,
        "zero_wind_replication": loss_rate(zero[0]) if zero else None,
        "arms_matching_baseline": indistinguishable,
        "strongest_wind_matching_baseline": max((row["mu"] for row in indistinguishable), default=None),
    }


# --- writing ----------------------------------------------------------------


def describe(records):
    losses = [record for record in records if record["outcome"] == "LOST"]
    steps = sorted(record["steps_completed"] for record in losses)
    burned = [record["burned_out_cells_final"] + record["burning_cells_final"] for record in records]
    return {
        **loss_rate(records),
        "median_step_of_loss": statistics.median(steps) if steps else None,
        "max_step_of_loss": steps[-1] if steps else None,
        "mean_cells_burned": round(statistics.fmean(burned), 1),
    }


def summarise(arms, axes):
    rows = []
    for key, records in sorted(arms.items(), key=lambda pair: [_numeric(v) for v in pair[0]]):
        rows.append({**dict(zip(axes, key)), **describe(records)})
    return rows


def _numeric(value):
    try:
        return float(value)
    except ValueError:
        return value


def write_arms_csv(sections, path):
    columns = ["sweep", "direction", "mu", "batch_size", "first_dir_prob", "n", "lost", "rate",
               "low", "high", "median_step_of_loss", "max_step_of_loss", "mean_cells_burned"]
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in sections:
            writer.writerow(row)


# --- main -------------------------------------------------------------------


def main():
    discarded = []
    cardinal = read_arms(HERE / "runs" / "cardinal", ("WIND_DIRECTION", "MU"), discarded)
    diagonal = read_arms(HERE / "runs" / "diagonal", ("FIRST_DIR", "SECOND_DIR", "MU"), discarded)
    if not cardinal:
        raise SystemExit("no cardinal arms found -- run experiments/20260810_wind/run.sh first")

    checks = {
        "paired_seeds": check_pairing({"cardinal": cardinal, "diagonal": diagonal}),
        "zero_wind": check_zero_wind_is_directionless(cardinal, diagonal),
        "line_fire": check_line_fire_prediction(cardinal),
        "against_baseline": compare_with_baseline(cardinal),
    }

    summary = {
        "cardinal": summarise(cardinal, ("direction", "mu")),
        "diagonal": summarise(diagonal, ("first_dir", "second_dir", "mu")),
        "checks": checks,
        "discarded_arms": discarded,
    }

    flat = []
    for row in summary["cardinal"]:
        flat.append({"sweep": "cardinal", **row})
    for row in summary["diagonal"]:
        flat.append({"sweep": "diagonal", "direction": f"{row['first_dir']}+{row['second_dir']}", **row})
    write_arms_csv(flat, HERE / "arms.csv")

    with open(HERE / "summary.json", "w") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")

    # --- the report to the terminal ---

    zero = checks["zero_wind"]
    arms = len(summary["cardinal"]) + len(summary["diagonal"])
    print(f"pairing: {checks['paired_seeds']} seeds name one ignition cell across all {arms} arms of the "
          "cardinal and diagonal sweeps")
    print(f"MU = 0: {zero['arms']} directions agree run for run, "
          f"loss rate {zero['rate']:.2f}% over {zero['n']} runs "
          f"(95% Wilson {zero['low']:.2f} - {zero['high']:.2f})")

    print("\nMU = 1 line fire prediction (ignitions beyond the first three cell leap)")
    print(f"{'direction':<10} {'strip':>6} {'predicted':>10} {'actual':>7} {'mismatch':>9} "
          f"{'near base':>10} {'rate':>8}")
    for row in checks["line_fire"]:
        mismatch = len(row["predicted_not_lost"]) + len(row["lost_not_predicted"])
        near = row["within_first_leap"]
        print(f"{row['direction']:<10} {row['upwind_strip_cells']:>6} {row['predicted_lost']:>10} "
              f"{row['actual_lost']:>7} {mismatch:>9} {near['lost']:>4}/{near['n']:<5} "
              f"{row['rate']:>7.2f}%")

    for name, axes in (("cardinal", ("direction", "mu")),
                       ("diagonal", ("first_dir", "second_dir", "mu"))):
        print(f"\n{name}")
        print(f"{'arm':<28} {'n':>5} {'lost':>5} {'rate':>8}   95% Wilson")
        for row in summary[name]:
            label = " ".join(str(row[axis]) for axis in axes)
            print(f"{label:<28} {row['n']:>5} {row['lost']:>5} {row['rate']:>7.2f}%   "
                  f"{row['low']:.2f} - {row['high']:.2f}")


if __name__ == "__main__":
    main()
