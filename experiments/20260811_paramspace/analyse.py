#!/usr/bin/env python3
"""Turns the sweep's raw per-arm output into one row per arm: the two key metrics and their intervals.

Reads runs/arms/*.json -- one JSON object per simulation, as sim/cli/ writes them -- joined onto
design.json, and produces

  * arms.csv       one row per arm: the eight swept parameters, the loss rate with its 95% Wilson
                   interval, both step metrics with their 95% t intervals, and the descriptives that
                   make a cluster readable afterwards. This is what cluster.py reads.
  * summary.json   the same numbers plus the sweep-wide distributions the report quotes.

Two metrics, because "number of steps to loss" is censored
----------------------------------------------------------
A run that survives its 100 steps never has a loss step, so a mean taken over lost runs alone is
conditioned on losing and is undefined for an arm that never loses. Both are recorded:

  steps_to_loss    mean over the lost runs only. Null for a 0% loss arm. This is the metric as asked
                   for, and it answers "when an arm loses, how fast".
  steps_survived   mean over every run, with a surviving run contributing BATCH_SIZE. Defined for every
                   arm, so this is the one that enters the clustering feature vector. It is a censored
                   mean, not a survival time: at the hard end it is a real duration, and at the easy end
                   it saturates at 100 and stops distinguishing anything. Both facts are in the report.

The Wilson interval is imported from tools/sweep.py rather than reimplemented, so that this experiment
and the sweep tool cannot disagree about what a 95% interval is; tests/tools/test_sweep.py pins it.

Run from the repository root:  python3 experiments/20260811_paramspace/analyse.py
"""

from __future__ import annotations

# python libraries

import argparse
import csv
import json
import math
import pathlib
import statistics
import sys

import numpy as np
from scipy import stats

# own python modules

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.sweep import wilson

import design as design_module  # noqa: E402 - after the sys.path insert above

HERE = pathlib.Path(__file__).resolve().parent

# the run length every arm was given, and so the value a surviving run's steps_survived saturates at
BATCH_SIZE = design_module.CONSTANTS["BATCH_SIZE"]


# --- statistics -------------------------------------------------------------


def loss_rate(records):
    """Loss rate and its 95% Wilson interval, as percentages."""
    trials = len(records)
    losses = sum(1 for record in records if record["outcome"] == "LOST")
    if trials == 0:
        return {"n": 0, "lost": 0, "rate": None, "low": None, "high": None}
    low, high = wilson(losses, trials)
    return {
        "n": trials,
        "lost": losses,
        "rate": 100.0 * losses / trials,
        "low": 100.0 * low,
        "high": 100.0 * high,
    }


def mean_interval(values):
    """Mean and its 95% t interval.

    A t interval rather than a normal one because an arm is 100 runs, not thousands, and because the
    step distributions are visibly skewed -- an arm that mostly loses early has a long right tail of
    runs that survived. The interval is on the *mean*, and says nothing about the spread of the runs;
    sd is reported alongside for that.
    """
    count = len(values)
    if count == 0:
        return {"n": 0, "mean": None, "sd": None, "low": None, "high": None}
    mean = float(statistics.fmean(values))
    if count == 1:
        return {"n": 1, "mean": mean, "sd": 0.0, "low": mean, "high": mean}
    sd = float(statistics.stdev(values))
    if sd == 0.0:
        # every run gave the same answer; the interval is the point, not a division by zero
        return {"n": count, "mean": mean, "sd": 0.0, "low": mean, "high": mean}
    half = stats.t.ppf(0.975, count - 1) * sd / math.sqrt(count)
    return {"n": count, "mean": mean, "sd": sd, "low": mean - half, "high": mean + half}


# --- reading ----------------------------------------------------------------


def load_arm(path):
    with open(path) as handle:
        return json.load(handle)


def load(runs_dir, arms):
    """Read every arm's results, checking them over before anything is summarised.

    Every check here exits rather than dropping rows. A sweep that half ran, or whose runs errored, is
    not a smaller sweep -- it is an unknown one, and quietly averaging what survived is how a bug gets
    reported as a result.
    """
    missing = [arm for arm in arms if not (runs_dir / "arms" / f"{arm['slug']}.json").exists()]
    if missing:
        raise SystemExit(
            f"{len(missing)} of {len(arms)} arms have no results file (first: {missing[0]['slug']}). "
            "Finish the sweep, or pass --arms to analyse the prefix that was run."
        )

    loaded = {}
    counts = set()
    for arm in arms:
        records = load_arm(runs_dir / "arms" / f"{arm['slug']}.json")

        failed = [record for record in records if record.get("error")]
        if failed:
            raise SystemExit(f"arm {arm['slug']}: {len(failed)} of {len(records)} runs errored, refusing "
                             f"to summarise. First was seed {failed[0]['seed']}: {failed[0]['error']}")

        undecided = [record for record in records if record["outcome"] not in ("WON", "LOST")]
        if undecided:
            raise SystemExit(f"arm {arm['slug']}: {len(undecided)} runs have no home base to lose "
                             "(outcome N/A), so the arm ran with ACTIVATE_FIREFIGHTING off")

        # Seeds are checked *within* an arm, not across the sweep. Arms are deliberately paired on the
        # fire -- run i of every arm uses the same seed -- so the sweep-wide seed set is 100 values
        # repeated 2048 times, and a global uniqueness check would fail by design. Inside an arm they
        # must still be distinct, or the arm is 100 copies of fewer measurements.
        seeds = {record["seed"] for record in records}
        if len(seeds) != len(records):
            raise SystemExit(f"arm {arm['slug']}: {len(records)} runs share only {len(seeds)} seeds, "
                             "so the runs within the arm are not independent")

        over = [record for record in records if record["steps_completed"] > BATCH_SIZE]
        if over:
            raise SystemExit(f"arm {arm['slug']}: {len(over)} runs ran past BATCH_SIZE={BATCH_SIZE}, "
                             "so the arm was not run at the design's run length")

        counts.add(len(records))
        loaded[arm["arm_id"]] = records

    if len(counts) != 1:
        raise SystemExit(f"arms have different run counts {sorted(counts)}: the loss rates are not "
                         "comparable and the Wilson intervals would be silently uneven")

    return loaded, counts.pop()


# --- summarising ------------------------------------------------------------


def summarise_arm(arm, records):
    """One arm: its parameters, the two key metrics, and the descriptives behind them."""
    losses = [record for record in records if record["outcome"] == "LOST"]

    rate = loss_rate(records)
    # conditioned on losing, so undefined for an arm that never does
    to_loss = mean_interval([record["steps_completed"] for record in losses])
    # every run, a survivor contributing BATCH_SIZE. Defined for every arm; saturates at the easy end
    survived = mean_interval([record["steps_completed"] for record in records])

    burned = [record["burned_out_cells_final"] for record in records]
    burning = [record["burning_cells_final"] for record in records]

    return {
        "arm_id": arm["arm_id"],
        "slug": arm["slug"],
        **{name: arm["params"][name] for name in design_module.DIMENSIONS},
        "WIND_DIRECTION": arm["params"]["WIND_DIRECTION"],
        "n": rate["n"],
        "lost": rate["lost"],
        "loss_rate": rate["rate"],
        "loss_rate_low": rate["low"],
        "loss_rate_high": rate["high"],
        "steps_to_loss": to_loss["mean"],
        "steps_to_loss_low": to_loss["low"],
        "steps_to_loss_high": to_loss["high"],
        "steps_to_loss_sd": to_loss["sd"],
        "steps_survived": survived["mean"],
        "steps_survived_low": survived["low"],
        "steps_survived_high": survived["high"],
        "steps_survived_sd": survived["sd"],
        # not in the clustering feature vector; these are what make a cluster interpretable afterwards
        "burned_out_mean": round(float(statistics.fmean(burned)), 1),
        "burning_final_mean": round(float(statistics.fmean(burning)), 1),
        "base_burning_mean": round(
            float(statistics.fmean(record["base_burning_steps"] for record in records)), 3),
        "wall_time_s": round(sum(record["wall_time_s"] for record in records), 1),
    }


ARM_COLUMNS = [
    "arm_id", "slug",
    "BHP", "MU", "WIND_DIRECTION", "BURNING_RATE", "FIRE_SPREAD_SPEED",
    "DENSITY_PROB", "FUEL_BOTTOM_LIMIT", "FUEL_UPPER_LIMIT",
    "n", "lost", "loss_rate", "loss_rate_low", "loss_rate_high",
    "steps_to_loss", "steps_to_loss_low", "steps_to_loss_high", "steps_to_loss_sd",
    "steps_survived", "steps_survived_low", "steps_survived_high", "steps_survived_sd",
    "burned_out_mean", "burning_final_mean", "base_burning_mean", "wall_time_s",
]


def write_arms_csv(rows, path):
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ARM_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda item: item["arm_id"]):
            writer.writerow({name: ("" if row[name] is None else row[name]) for name in ARM_COLUMNS})


def distribution(values):
    """The five numbers the report quotes for a sweep-wide spread."""
    values = np.asarray([value for value in values if value is not None], dtype=float)
    if values.size == 0:
        return {"n": 0}
    return {
        "n": int(values.size),
        "min": float(values.min()),
        "p25": float(np.percentile(values, 25)),
        "median": float(np.median(values)),
        "p75": float(np.percentile(values, 75)),
        "max": float(values.max()),
        "mean": float(values.mean()),
    }


# --- entry point ------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arms", type=int, default=0,
                        help="analyse only the first N arms, matching a run.py --arms smoke test")
    parser.add_argument("--runs-dir", default=None, help="results directory (default runs/)")
    # so that a smoke test reading a scratch --runs-dir cannot overwrite the real arms.csv beside it
    parser.add_argument("--out-dir", default=None,
                        help="where arms.csv and summary.json go (default beside this script)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    arms = design_module.load()
    if args.arms:
        arms = arms[:args.arms]
    runs_dir = pathlib.Path(args.runs_dir) if args.runs_dir else HERE / "runs"
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else HERE
    out_dir.mkdir(parents=True, exist_ok=True)

    loaded, runs_per_arm = load(runs_dir, arms)
    rows = [summarise_arm(arm, loaded[arm["arm_id"]]) for arm in arms]

    write_arms_csv(rows, out_dir / "arms.csv")

    rates = [row["loss_rate"] for row in rows]
    # how much of the design landed on each end. An experiment about the difficulty surface has to say
    # how much of its budget it spent measuring the two places where the surface is flat.
    saturated_high = sum(1 for rate in rates if rate >= 100.0)
    saturated_low = sum(1 for rate in rates if rate <= 0.0)

    summary = {
        "arms": len(rows),
        "runs_per_arm": runs_per_arm,
        "runs": len(rows) * runs_per_arm,
        "design_seed": design_module.DESIGN_SEED,
        "seed_base": design_module.SEED_BASE,
        "batch_size": BATCH_SIZE,
        "constants": {name: list(value) if isinstance(value, tuple) else value
                      for name, value in design_module.CONSTANTS.items()},
        "ranges": {name: list(value) for name, value in design_module.RANGES.items()},
        "loss_rate": distribution(rates),
        "steps_to_loss": distribution([row["steps_to_loss"] for row in rows]),
        "steps_survived": distribution([row["steps_survived"] for row in rows]),
        "saturation": {
            "always_lost": saturated_high,
            "never_lost": saturated_low,
            "always_lost_share": 100.0 * saturated_high / len(rows),
            "never_lost_share": 100.0 * saturated_low / len(rows),
            # steps_to_loss is undefined for these, which is the censoring the report has to declare
            "no_steps_to_loss": sum(1 for row in rows if row["steps_to_loss"] is None),
        },
        # the mean half width of an arm's Wilson interval, which is the resolution the whole experiment
        # has at this runs-per-arm and the number a reader needs before believing any single arm
        "mean_wilson_half_width": float(np.mean(
            [(row["loss_rate_high"] - row["loss_rate_low"]) / 2.0 for row in rows])),
        "by_wind_direction": {
            direction: distribution([row["loss_rate"] for row in rows
                                     if row["WIND_DIRECTION"] == direction])
            for direction in design_module.COMPASS
        },
        "wall_time_s": round(sum(row["wall_time_s"] for row in rows), 1),
    }

    with open(out_dir / "summary.json", "w") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")

    # --- the table -----------------------------------------------------------

    print(f"{len(rows)} arms x {runs_per_arm} runs = {len(rows) * runs_per_arm} runs")
    print(f"arms.csv -> {out_dir / 'arms.csv'}")
    print(f"summary.json -> {out_dir / 'summary.json'}")
    print()

    print(f"{'metric':<18} {'min':>8} {'p25':>8} {'median':>8} {'p75':>8} {'max':>8}")
    for name in ("loss_rate", "steps_to_loss", "steps_survived"):
        spread = summary[name]
        if not spread["n"]:
            print(f"{name:<18} {'-':>8}")
            continue
        print(f"{name:<18} {spread['min']:>8.2f} {spread['p25']:>8.2f} {spread['median']:>8.2f} "
              f"{spread['p75']:>8.2f} {spread['max']:>8.2f}")

    saturation = summary["saturation"]
    print()
    print(f"always lost (100%): {saturation['always_lost']} arms "
          f"({saturation['always_lost_share']:.1f}%)")
    print(f"never lost   (0%): {saturation['never_lost']} arms "
          f"({saturation['never_lost_share']:.1f}%), and so no steps_to_loss")
    print(f"mean 95% Wilson half width: +/- {summary['mean_wilson_half_width']:.2f} points per arm")

    print()
    print(f"{'wind':<12} {'arms':>6} {'mean loss rate':>16}")
    for direction, spread in summary["by_wind_direction"].items():
        if not spread["n"]:
            continue
        print(f"{direction:<12} {spread['n']:>6} {spread['mean']:>15.2f}%")

    # the hardest and easiest handful, which is the first thing worth eyeballing
    ranked = sorted(rows, key=lambda row: (-row["loss_rate"], row["steps_survived"]))
    print()
    print("hardest 5 arms:")
    for row in ranked[:5]:
        print(f"  {row['slug']:<58} loss {row['loss_rate']:>6.1f}%  "
              f"survived {row['steps_survived']:>6.1f} steps")
    print("easiest 5 arms:")
    for row in ranked[-5:]:
        print(f"  {row['slug']:<58} loss {row['loss_rate']:>6.1f}%  "
              f"survived {row['steps_survived']:>6.1f} steps")

    return 0


if __name__ == "__main__":
    sys.exit(main())
