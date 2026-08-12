#!/usr/bin/env python3
"""Runs the parameter space sweep: every arm of design.py, 100 simulations each.

204,800 runs, which is hours of wall time. Written to be started, interrupted and resumed.

Why this does not go through tools/sweep.py
-------------------------------------------
tools/sweep.py scan runs each arm in its own headless.py subprocess, because apply_overrides() and
seed_simulation() mutate the global config module and arms sharing a process would leak settings into one
another. That is the right trade at 73 arms. At 2048 it is an hour of interpreter and mesa startup, and
sweep.py can only express a cartesian product anyway, which a Sobol design is not.

The isolation the subprocess was buying is already available a level down: sim/cli/batch.run_batch()
takes a *heterogeneous* list of RunConfig, and sim/cli/runner.run_simulation() applies that config's own
overrides and seed inside whichever worker picks it up. So the whole sweep runs as one flat list of
(arm, run) pairs over one process pool.

    The invariant that makes this safe: workers are reused, and apply_overrides() sets attributes on the
    config module without resetting anything first. A setting that arm A overrides and arm B does not
    would keep A's value when B lands on A's worker. Every RunConfig must therefore carry the *complete*
    override dict -- every constant and every swept parameter -- so that each run fully overwrites the
    one before it. assert_uniform_overrides() below refuses to submit anything else, and
    tests/experiments/test_paramspace_design.py pins it.

Seeding
-------
Run i of *every* arm uses SEED_BASE + i, so the arms are paired on the fire: they see the same 100
ignitions, and the difference between two arms is not partly the difference between two sets of fires.
This is the convention tools/sweep.py already follows for the same reason. The cost is that 100 distinct
ignitions back the entire sweep, so every arm's absolute loss rate carries the same fire sample error --
fine for the comparison this experiment is about, and stated in the report.

Reads design.json. Writes runs/arms/<slug>.json (one file per arm, as sim/cli/ writes results) and,
once every arm is in, runs/results.csv in long format.

Run from the repository root:

    python3 experiments/20260811_paramspace/run.py --dry-run          # print the design, run nothing
    python3 experiments/20260811_paramspace/run.py --arms 20          # smoke test, about a minute
    python3 experiments/20260811_paramspace/run.py --workers 10       # the real thing, hours
"""

from __future__ import annotations

# python libraries

import argparse
import csv
import json
import os
import pathlib
import sys
import time
from dataclasses import asdict

# own python modules

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sim.cli.batch import run_batch
from sim.cli.overrides import apply_overrides
from sim.cli.reporting import configure_logging

import design as design_module  # noqa: E402 - after the sys.path insert above

HERE = pathlib.Path(__file__).resolve().parent

# no UAVs fly, so no policy is ever consulted; a registered name still has to be passed
POLICY = "random"


# --- building the work ------------------------------------------------------


def build_configs(arms, runs_per_arm, seed_base):
    """One RunConfig per (arm, run) pair, each carrying the complete override dict."""
    from sim.cli.runner import RunConfig

    configs = []
    for arm in arms:
        overrides = dict(arm["settings"])
        # BASE_SIZE comes back from JSON as a list; the model indexes it either way, but the config
        # record and the validate() bounds both read better as the tuple config.py declares
        if isinstance(overrides.get("BASE_SIZE"), list):
            overrides["BASE_SIZE"] = tuple(overrides["BASE_SIZE"])

        for index in range(runs_per_arm):
            configs.append(RunConfig(
                # globally unique: run_batch sorts on it and _collect keys crashed runs by it
                run_id=arm["arm_id"] * runs_per_arm + index,
                steps=overrides["BATCH_SIZE"],
                seed=seed_base + index,
                overrides=dict(overrides),
                log_every=0,
                policy=POLICY,
            ))
    return configs


def assert_uniform_overrides(configs):
    """Every config must override exactly the same set of constants. See the module docstring.

    A key present in one arm and absent from another is the one way this runner can silently produce
    wrong numbers: the absent arm inherits whatever the worker was left holding. Checked once, here,
    rather than trusted.
    """
    if not configs:
        return
    expected = frozenset(configs[0].overrides)
    for config in configs:
        keys = frozenset(config.overrides)
        if keys != expected:
            missing = sorted(expected - keys)
            extra = sorted(keys - expected)
            raise SystemExit(
                f"run {config.run_id} overrides a different set of constants than run "
                f"{configs[0].run_id}: missing {missing}, extra {extra}. Every arm must override every "
                "constant, or a setting leaks from one arm into the next through a reused worker."
            )


# --- running ----------------------------------------------------------------


def arm_path(runs_dir, arm):
    return runs_dir / "arms" / f"{arm['slug']}.json"


def pending_arms(arms, runs_dir, resume):
    """The arms still to run: all of them, or the ones with no results file yet."""
    if not resume:
        return list(arms)
    return [arm for arm in arms if not arm_path(runs_dir, arm).exists()]


def run_group(group, runs_per_arm, seed_base, workers, log_level, log, runs_dir):
    """Run every arm of one group and write each arm's results out. Returns runs completed."""
    configs = build_configs(group, runs_per_arm, seed_base)
    assert_uniform_overrides(configs)

    results = run_batch(configs, workers, "process", log_level, log)

    by_arm = {arm["arm_id"]: [] for arm in group}
    for result in results:
        by_arm[result.run_id // runs_per_arm].append(result)

    errored = 0
    for arm in group:
        records = []
        for result in sorted(by_arm[arm["arm_id"]], key=lambda item: item.run_id):
            record = asdict(result)
            # 'outcome' is a property, so asdict() does not carry it; sim/cli/main.py adds it the same
            # way when it writes --output, and every downstream reader expects it to be there
            record["outcome"] = result.outcome
            record["arm_id"] = arm["arm_id"]
            records.append(record)
            if result.error:
                errored += 1

        path = arm_path(runs_dir, arm)
        # written whole rather than appended, so a half written file cannot be mistaken for a finished arm
        temporary = path.with_suffix(".json.partial")
        with open(temporary, "w") as handle:
            json.dump(records, handle)
        temporary.replace(path)

    return len(results), errored


# --- the results table ------------------------------------------------------


# columns of runs/results.csv: the arm's identity first, then the per run outcome. Long format, one row
# per simulation, following the layout tools/sweep.py writes so the two can be read the same way.
CSV_COLUMNS = [
    "arm_id", "slug",
    "BHP", "MU", "WIND_DIRECTION", "BURNING_RATE",
    "FIRE_SPREAD_SPEED", "DENSITY_PROB", "FUEL_BOTTOM_LIMIT", "FUEL_UPPER_LIMIT",
    "run_id", "seed", "outcome", "lost", "steps_completed",
    "fire_start_row", "fire_start_col", "wind_initial",
    "base_burning_steps", "burning_cells_final", "burned_out_cells_final",
    "wall_time_s", "error",
]


def write_results_csv(arms, runs_dir, path):
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for arm in arms:
            source = arm_path(runs_dir, arm)
            if not source.exists():
                continue
            with open(source) as source_handle:
                records = json.load(source_handle)
            params = arm["params"]
            identity = [arm["arm_id"], arm["slug"],
                        params["BHP"], params["MU"], params["WIND_DIRECTION"],
                        params["BURNING_RATE"], params["FIRE_SPREAD_SPEED"],
                        params["DENSITY_PROB"], params["FUEL_BOTTOM_LIMIT"],
                        params["FUEL_UPPER_LIMIT"]]
            for record in records:
                position = record.get("fire_start_pos") or [None, None]
                writer.writerow(identity + [
                    record["run_id"], record["seed"], record["outcome"],
                    int(bool(record["lost"])), record["steps_completed"],
                    position[0], position[1], record.get("wind_initial", ""),
                    record["base_burning_steps"], record["burning_cells_final"],
                    record["burned_out_cells_final"],
                    record["wall_time_s"], record.get("error") or "",
                ])


# --- entry point ------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workers", type=int, default=0,
                        help="worker processes; 0 means one per CPU (default)")
    parser.add_argument("--arms", type=int, default=0,
                        help="run only the first N arms of the design, for a smoke test")
    parser.add_argument("--runs", type=int, default=0,
                        help=f"simulations per arm (default {design_module.RUNS_PER_ARM})")
    parser.add_argument("--group", type=int, default=20,
                        help="arms submitted to the pool at once; also the checkpoint granularity")
    parser.add_argument("--seed", type=int, default=design_module.SEED_BASE,
                        help="base seed; run i of every arm uses seed + i")
    parser.add_argument("--out", default=None, help="results directory (default runs/ beside this file)")
    parser.add_argument("--no-resume", action="store_true",
                        help="re-run arms that already have a results file")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be run and exit without simulating anything")
    parser.add_argument("--log-level", default="ERROR",
                        help="per-run log level; ERROR keeps the progress readable (default)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    arms = design_module.load()
    if args.arms:
        arms = arms[:args.arms]
    runs_per_arm = args.runs or design_module.RUNS_PER_ARM
    workers = args.workers or os.cpu_count() or 1

    runs_dir = pathlib.Path(args.out) if args.out else HERE / "runs"
    (runs_dir / "arms").mkdir(parents=True, exist_ok=True)

    # fail before any worker starts if the constants do not validate together -- the same fail fast check
    # headless.py does in the parent, and the reason a bad range in design.py costs a second not an hour
    apply_overrides(dict(arms[0]["settings"]))

    todo = pending_arms(arms, runs_dir, not args.no_resume)
    done = len(arms) - len(todo)

    print(f"{len(arms)} arms x {runs_per_arm} runs = {len(arms) * runs_per_arm} runs")
    print(f"{done} arms already have results, {len(todo)} to run "
          f"({len(todo) * runs_per_arm} runs) on {workers} workers")
    print(f"seeds {args.seed} .. {args.seed + runs_per_arm - 1}, the same block in every arm")
    print(f"results -> {runs_dir / 'arms'}")

    if args.dry_run:
        print("\n--dry-run: nothing was simulated")
        return 0
    if not todo:
        print("nothing to do")
        write_results_csv(arms, runs_dir, runs_dir / "results.csv")
        return 0

    log = configure_logging(args.log_level, None)

    started = time.perf_counter()
    completed = 0
    errored = 0
    groups = [todo[index:index + args.group] for index in range(0, len(todo), args.group)]

    for number, group in enumerate(groups, start=1):
        group_started = time.perf_counter()
        ran, group_errors = run_group(group, runs_per_arm, args.seed, workers,
                                      args.log_level, log, runs_dir)
        completed += ran
        errored += group_errors

        elapsed = time.perf_counter() - started
        rate = completed / elapsed if elapsed else 0.0
        remaining = (len(todo) * runs_per_arm - completed) / rate if rate else 0.0
        print(f"group {number}/{len(groups)}  "
              f"{completed}/{len(todo) * runs_per_arm} runs  "
              f"{ran / (time.perf_counter() - group_started):.1f} runs/s  "
              f"elapsed {_duration(elapsed)}  remaining ~{_duration(remaining)}"
              + (f"  ERRORS {errored}" if errored else ""),
              flush=True)

    write_results_csv(arms, runs_dir, runs_dir / "results.csv")

    print(f"\n{completed} runs in {_duration(time.perf_counter() - started)}")
    print(f"results.csv -> {runs_dir / 'results.csv'}")
    if errored:
        # a run that raised is not a measurement, and analyse.py refuses to summarise over one
        print(f"{errored} run(s) errored", file=sys.stderr)
        return 1
    return 0


def _duration(seconds):
    seconds = int(seconds)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m{seconds:02d}s"


if __name__ == "__main__":
    sys.exit(main())
