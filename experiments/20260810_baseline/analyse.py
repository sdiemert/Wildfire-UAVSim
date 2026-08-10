#!/usr/bin/env python3
"""Turns the raw headless.py output of the no-UAV baseline into the numbers in the report.

Reads runs/no-uav.json -- one JSON object per simulation, as sim/cli/ writes it -- and produces

  * results.csv   one row per run, long format: seed, outcome, the step it ended on, the ignition cell,
                  and the Chebyshev distance from that cell to the home base footprint. The JSON alone
                  does not carry the distance, and it is the covariate the loss rate turns on.
  * summary.json  the loss rate, its 95% Wilson interval, and the same broken down by distance band.

runs/control-20-steps.json is folded in as well. The main arm loses every run, and a measurement with no
variation cannot tell "the scenario is always lost" apart from "the outcome field is stuck at LOST", so
the control arm re-runs the same configuration truncated to 20 steps -- short enough that a good share of
the fires have not reached the base yet -- on a seed block the main arm never touched. Its loss rate is
also predicted from the main arm's steps-to-loss distribution, and the two have to agree.

The Wilson interval is imported from tools/sweep.py rather than reimplemented, so that this experiment
and the sweep tool cannot disagree about what a 95% interval is; tests/tools/test_sweep.py pins it.

Run from the repository root:  python3 experiments/20260810_baseline/analyse.py
"""

# python libraries

import csv
import json
import math
import pathlib
import statistics
import sys

# own python modules

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.sweep import wilson

HERE = pathlib.Path(__file__).resolve().parent

# The arm was run with BASE_POSITION = None on a 100x100 grid, which anchors the base a quarter of the
# way in at (HEIGHT/4, WIDTH/4) and covers a BASE_SIZE footprint from there -- see WildFireModel.
# base_footprint(). Hard-coded here rather than imported, because importing the model would pull mesa in
# to answer a question about four cells.
BASE_CELLS = [(25, 25), (25, 26), (26, 25), (26, 26)]

# distance bands the loss rate is reported over. The fire spreads at a little under two cells a step, so
# a 100 step run reaches a bounded radius: the bands are chosen either side of it.
BANDS = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 140)]


# --- statistics -------------------------------------------------------------


# Chebyshev distance from a cell to the nearest cell of the base footprint. Chebyshev rather than
# Euclidean because the fire spreads through a Moore neighbourhood, so it is the number of spread events
# that separates the ignition from the base, not the straight line length.
def distance_to_base(position):
    return min(max(abs(position[0] - cell[0]), abs(position[1] - cell[1])) for cell in BASE_CELLS)


# loss rate and its 95% Wilson interval over a list of run records, as percentages
def loss_rate(records):
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


# --- reading ----------------------------------------------------------------


def load(path):
    with open(path) as handle:
        records = json.load(handle)

    # a run that raised is not a measurement of anything, and silently counting it as a win or a loss is
    # the way an experiment reports a bug as a result
    failed = [record for record in records if record.get("error")]
    if failed:
        raise SystemExit(f"{len(failed)} of {len(records)} runs errored, refusing to summarise: "
                         f"first was seed {failed[0]['seed']}: {failed[0]['error']}")

    undecided = [record for record in records if record["outcome"] not in ("WON", "LOST")]
    if undecided:
        raise SystemExit(f"{len(undecided)} runs have no home base to lose (outcome N/A): the arm was "
                         "run with ACTIVATE_FIREFIGHTING off, which is not the baseline")

    seeds = {record["seed"] for record in records}
    if len(seeds) != len(records):
        raise SystemExit(f"{len(records)} runs share only {len(seeds)} seeds: the runs are not independent")

    return records


# --- writing ----------------------------------------------------------------


def write_results_csv(records, path):
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["run_id", "seed", "outcome", "lost", "steps_completed",
                         "fire_start_row", "fire_start_col", "distance_to_base",
                         "base_burning_steps", "burning_cells_final", "burned_out_cells_final"])
        for record in sorted(records, key=lambda r: r["seed"]):
            row, col = record["fire_start_pos"]
            writer.writerow([record["run_id"], record["seed"], record["outcome"],
                             int(record["lost"]), record["steps_completed"],
                             row, col, distance_to_base((row, col)),
                             record["base_burning_steps"], record["burning_cells_final"],
                             record["burned_out_cells_final"]])


def main():
    records = load(HERE / "runs" / "no-uav.json")
    write_results_csv(records, HERE / "results.csv")

    overall = loss_rate(records)

    bands = []
    for low, high in BANDS:
        inside = [r for r in records if low <= distance_to_base(r["fire_start_pos"]) < high]
        bands.append({"from": low, "to": high, **loss_rate(inside)})

    losses = [r for r in records if r["outcome"] == "LOST"]
    wins = [r for r in records if r["outcome"] == "WON"]
    steps_to_loss = sorted(r["steps_completed"] for r in losses)
    distances = sorted(distance_to_base(r["fire_start_pos"]) for r in records)

    summary = {
        "runs": len(records),
        "seed_base": min(r["seed"] for r in records),
        "seed_top": max(r["seed"] for r in records),
        "overall": overall,
        "by_distance": bands,
        "steps_to_loss": {
            "min": steps_to_loss[0] if steps_to_loss else None,
            "median": statistics.median(steps_to_loss) if steps_to_loss else None,
            "mean": round(statistics.fmean(steps_to_loss), 2) if steps_to_loss else None,
            "p95": steps_to_loss[math.ceil(0.95 * len(steps_to_loss)) - 1] if steps_to_loss else None,
            "max": steps_to_loss[-1] if steps_to_loss else None,
        },
        "ignition_distance": {
            "min": distances[0],
            "median": statistics.median(distances),
            "mean": round(statistics.fmean(distances), 2),
            "max": distances[-1],
            "max_lost": max((distance_to_base(r["fire_start_pos"]) for r in losses), default=None),
            "min_won": min((distance_to_base(r["fire_start_pos"]) for r in wins), default=None),
        },
        "wall_time_s": round(sum(r["wall_time_s"] for r in records), 1),
    }

    # the control arm, and the prediction it is checked against
    control = load(HERE / "runs" / "control-20-steps.json")
    truncation = 20
    predicted = 100.0 * sum(1 for r in records if r["steps_completed"] <= truncation) / len(records)
    summary["control"] = {
        "batch_size": truncation,
        "seed_base": min(r["seed"] for r in control),
        "predicted_rate": round(predicted, 2),
        **loss_rate(control),
    }

    with open(HERE / "summary.json", "w") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")

    print(f"n = {overall['n']}   lost = {overall['lost']}   "
          f"loss rate = {overall['rate']:.2f}%   95% Wilson {overall['low']:.2f} - {overall['high']:.2f}")
    print(f"{'distance to base':<20} {'n':>6} {'lost':>6} {'rate':>8}   95% Wilson")
    for band in bands:
        label = f"[{band['from']}, {band['to']})"
        if band["n"] == 0:
            print(f"{label:<20} {0:>6}")
            continue
        print(f"{label:<20} {band['n']:>6} {band['lost']:>6} {band['rate']:>7.2f}%   "
              f"{band['low']:.2f} - {band['high']:.2f}")
    print(f"steps to loss: median {summary['steps_to_loss']['median']}, "
          f"max {summary['steps_to_loss']['max']}")

    check = summary["control"]
    print(f"control at BATCH_SIZE={check['batch_size']}: n = {check['n']}   lost = {check['lost']}   "
          f"loss rate = {check['rate']:.2f}%   95% Wilson {check['low']:.2f} - {check['high']:.2f}   "
          f"(predicted {check['predicted_rate']:.2f}%)")


if __name__ == "__main__":
    main()
