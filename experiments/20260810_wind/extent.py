#!/usr/bin/env python3
"""Reads the extent sweep: what the wind does to the fire, as opposed to what it does to the base.

The loss rate is flat at 100% from MU = 0 to MU = 0.85, and the obvious reading of a flat line is that the
knob is not connected. It is connected. Over that same range the wind turns a fire that burns the whole
map into one that burns a fifth of it -- it just does not change the answer to the only question the base
asks, which is whether the fire arrives at all within a hundred steps.

This is a separate script from analyse.py because the sweep is a separate kind of measurement. Its arms
run with the home base switched off, so every run goes the full hundred steps instead of stopping when the
base falls, and the burned area is not confounded with how long the run happened to last. The price is
that these runs have no outcome -- analyse.py rejects an N/A outcome, and should.

Run from the repository root:  python3 experiments/20260810_wind/extent.py
"""

# python libraries

import csv
import json
import pathlib
import statistics

HERE = pathlib.Path(__file__).resolve().parent

CELLS = 100 * 100


def main():
    path = HERE / "runs" / "extent" / "runs.csv"
    if not path.exists():
        raise SystemExit(f"{path} is missing -- run experiments/20260810_wind/run.sh first")

    arms = {}
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            if row["error"]:
                raise SystemExit(f"a run of arm {row['arm']!r} errored: {row['error']}")
            # the base is off on purpose here, so N/A is the only outcome that should appear. Anything
            # else means the sweep ran with a base after all and the areas are truncated by its loss.
            if row["outcome"] != "N/A":
                raise SystemExit(f"arm {row['arm']!r} has outcome {row['outcome']!r}; this sweep is "
                                 "supposed to run with ACTIVATE_FIREFIGHTING off")
            if int(row["steps_completed"]) != 100:
                raise SystemExit(f"a run of arm {row['arm']!r} stopped at {row['steps_completed']} steps; "
                                 "the areas are only comparable if every run lasted the same time")
            burned = int(row["burning_cells_final"]) + int(row["burned_out_cells_final"])
            arms.setdefault(float(row["MU"]), []).append(burned)

    rows = []
    for mu, burned in sorted(arms.items()):
        rows.append({
            "mu": mu,
            "n": len(burned),
            "mean_cells": round(statistics.fmean(burned), 1),
            "share_of_grid": round(100.0 * statistics.fmean(burned) / CELLS, 2),
            "median_cells": statistics.median(burned),
            "min_cells": min(burned),
            "max_cells": max(burned),
        })

    with open(HERE / "extent.json", "w") as handle:
        json.dump(rows, handle, indent=2)
        handle.write("\n")

    print(f"{'MU':>7} {'n':>5} {'mean cells':>11} {'% of grid':>10} {'min':>7} {'max':>7}")
    for row in rows:
        print(f"{row['mu']:>7} {row['n']:>5} {row['mean_cells']:>11} {row['share_of_grid']:>9}% "
              f"{row['min_cells']:>7} {row['max_cells']:>7}")


if __name__ == "__main__":
    main()
