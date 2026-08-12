#!/usr/bin/env python3
"""Draws the report's figures from the analysis output.

Reads clusters.csv and cluster-summary.json and writes PNGs into figures/. report.py inlines them as
base64 data URIs, so the HTML report stays a single file that can be mailed around, and the Markdown
report references them as ordinary relative paths.

matplotlib rather than the hand written SVG of experiments/20260810_wind/figures.py. That file draws
categorical line charts, which are worth 200 lines of generator to keep the report dependency free; a
2048 point PCA scatter and a six panel small multiple are not. matplotlib is already a declared
dependency and, until now, an unused one.

Run from the repository root:  python3 experiments/20260811_paramspace/figures.py
"""

from __future__ import annotations

# python libraries

import argparse
import csv
import json
import pathlib
import sys

import matplotlib

# no display is attached when this runs from a terminal or a script; Agg has to be selected before
# pyplot is imported or matplotlib picks an interactive backend and fails
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402 - must follow matplotlib.use
import numpy as np  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent

# Clusters are coloured by difficulty *rank*, not by label number, so the colour reads as the ranking:
# dark red is hardest, blue is easiest. The ramp is interpolated across however many clusters there
# turned out to be rather than taking the first k of a fixed list -- a two cluster fit taking the first
# two entries of a red-to-blue list would draw both of them red.
RAMP = ["#8c1d18", "#c0392b", "#e07b39", "#e6b422", "#7fb069", "#3f8f6d", "#2e6f9e", "#3b4f8f"]


def rank_colour(rank, total):
    """Colour for difficulty rank 1..total, spread over the whole ramp."""
    if total <= 1:
        return RAMP[0]
    return RAMP[round((rank - 1) * (len(RAMP) - 1) / (total - 1))]


# short compass labels for the categorical panel, in config.WIND_HEADINGS order
COMPASS_SHORT = {
    "NORTH": "N", "NORTH_EAST": "NE", "EAST": "E", "SOUTH_EAST": "SE",
    "SOUTH": "S", "SOUTH_WEST": "SW", "WEST": "W", "NORTH_WEST": "NW",
}

DPI = 150

# the eight swept parameters as they are drawn in the small multiples, with readable axis labels
PARAMETERS = [
    ("BHP", "base health points (BHP)"),
    ("MU", "wind contrast (MU)"),
    ("BURNING_RATE", "burning rate"),
    ("FIRE_SPREAD_SPEED", "fire spread speed (steps/update)"),
    ("DENSITY_PROB", "vegetation density"),
    ("FUEL_BOTTOM_LIMIT", "fuel lower limit"),
    ("FUEL_UPPER_LIMIT", "fuel upper limit"),
    ("WIND_DIRECTION", "wind direction"),
]


# --- reading ----------------------------------------------------------------


def load(in_dir):
    with open(in_dir / "clusters.csv") as handle:
        rows = list(csv.DictReader(handle))
    with open(in_dir / "cluster-summary.json") as handle:
        summary = json.load(handle)

    for row in rows:
        for name in ("BHP", "BURNING_RATE", "FIRE_SPREAD_SPEED", "FUEL_BOTTOM_LIMIT",
                     "FUEL_UPPER_LIMIT", "cluster", "difficulty_rank"):
            row[name] = int(row[name])
        for name in ("MU", "DENSITY_PROB", "loss_rate", "steps_survived", "difficulty"):
            row[name] = float(row[name])
    return rows, summary


def colours_by_rank(summary):
    """Map a cluster label to its colour, chosen by difficulty rank rather than by label number."""
    total = len(summary["clusters"])
    return {cluster["cluster"]: rank_colour(cluster["rank"], total)
            for cluster in summary["clusters"]}


def _style(axis):
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.grid(True, alpha=0.25, linewidth=0.6)
    axis.set_axisbelow(True)


def _save(figure, path):
    figure.tight_layout()
    figure.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(figure)
    return path


# --- the figures ------------------------------------------------------------


def figure_selection(summary, path):
    """Silhouette and inertia against k: how the number of clusters was chosen, and how clearly."""
    curve = summary["selection_curve"]
    ks = [entry["k"] for entry in curve]

    figure, (left, right) = plt.subplots(1, 2, figsize=(10, 3.6))

    left.plot(ks, [entry["silhouette"] for entry in curve], marker="o", color="#8c1d18")
    left.axvline(summary["k"], color="#2b2b2b", linestyle="--", linewidth=1)
    left.set_xlabel("k")
    left.set_ylabel("silhouette score")
    left.set_title(f"silhouette (chosen k = {summary['k']})")

    right.plot(ks, [entry["inertia"] for entry in curve], marker="o", color="#2e6f9e")
    right.axvline(summary["k"], color="#2b2b2b", linestyle="--", linewidth=1)
    right.set_xlabel("k")
    right.set_ylabel("within-cluster sum of squares")
    right.set_title("elbow")

    for axis in (left, right):
        _style(axis)
    return _save(figure, path)


def figure_pca(summary, path):
    """The clustering space projected to two dimensions, coloured by cluster."""
    points = np.asarray(summary["pca"]["points"], dtype=float)
    labels = np.asarray(summary["pca"]["labels"], dtype=int)
    colours = colours_by_rank(summary)
    ratio = summary["pca"]["explained_variance_ratio"]

    figure, axis = plt.subplots(figsize=(7.5, 6))
    for cluster in summary["clusters"]:
        mask = labels == cluster["cluster"]
        axis.scatter(points[mask, 0], points[mask, 1],
                     s=14, alpha=0.65, linewidths=0,
                     color=colours[cluster["cluster"]],
                     label=f"{cluster['label']} (n={cluster['arms']}, "
                           f"{cluster['loss_rate']['mean']:.0f}% lost)")

    axis.set_xlabel(f"PC1 ({100 * ratio[0]:.1f}% of variance)")
    axis.set_ylabel(f"PC2 ({100 * ratio[1]:.1f}% of variance)")
    axis.set_title("the clustering space, projected")
    axis.legend(frameon=False, fontsize=8, loc="best")
    _style(axis)
    return _save(figure, path)


def figure_parameters(rows, summary, path):
    """Loss rate against each swept parameter, coloured by cluster.

    This is the figure that says which parameters the clusters are actually organised around: a
    parameter whose panel shows the colours stacked in bands separates the clusters, and one where they
    are mixed does not.
    """
    colours = colours_by_rank(summary)
    point_colours = [colours[row["cluster"]] for row in rows]

    figure, axes = plt.subplots(2, 4, figsize=(14, 6.5), sharey=True)

    for axis, (name, label) in zip(axes.flat, PARAMETERS):
        if name == "WIND_DIRECTION":
            # categorical: jitter within the compass slot so 2048 points do not stack into 8 bars.
            # Slots follow the compass, not the alphabet, so neighbouring headings sit side by side.
            present = {row["WIND_DIRECTION"] for row in rows}
            order = {value: index for index, value
                     in enumerate(name for name in COMPASS_SHORT if name in present)}
            # seeded: the jitter is decoration, and a figure that moved every time it was regenerated
            # would make the report's diffs unreadable
            rng = np.random.default_rng(0)
            x = np.asarray([order[row["WIND_DIRECTION"]] for row in rows], dtype=float)
            x = x + rng.uniform(-0.3, 0.3, size=x.size)
            axis.set_xticks(range(len(order)))
            axis.set_xticklabels([COMPASS_SHORT[value] for value in order], fontsize=8)
        else:
            x = np.asarray([row[name] for row in rows], dtype=float)

        axis.scatter(x, [row["loss_rate"] for row in rows],
                     s=6, alpha=0.5, linewidths=0, color=point_colours)
        axis.set_xlabel(label, fontsize=9)
        _style(axis)

    for axis in axes[:, 0]:
        axis.set_ylabel("loss rate (%)")
    figure.suptitle("loss rate against each swept parameter, coloured by cluster", fontsize=11)
    return _save(figure, path)


def figure_outcomes(rows, summary, path):
    """The two key metrics against each other. Shows the censoring at 100 steps directly."""
    colours = colours_by_rank(summary)

    figure, axis = plt.subplots(figsize=(7.5, 5.5))
    for cluster in summary["clusters"]:
        members = [row for row in rows if row["cluster"] == cluster["cluster"]]
        axis.scatter([row["steps_survived"] for row in members],
                     [row["loss_rate"] for row in members],
                     s=12, alpha=0.6, linewidths=0,
                     color=colours[cluster["cluster"]], label=cluster["label"])

    axis.set_xlabel("mean steps survived (censored at 100)")
    axis.set_ylabel("loss rate (%)")
    axis.set_title("the two key metrics, one point per configuration")
    axis.legend(frameon=False, fontsize=8)
    _style(axis)
    return _save(figure, path)


def figure_difficulty(summary, path):
    """Cluster difficulty, hardest first, with the spread of the arms inside each."""
    clusters = summary["clusters"]
    colours = colours_by_rank(summary)
    positions = np.arange(len(clusters))

    figure, (left, right) = plt.subplots(1, 2, figsize=(11, 4.2))

    left.bar(positions, [cluster["difficulty"] for cluster in clusters],
             yerr=[cluster["difficulty_sd"] for cluster in clusters],
             color=[colours[cluster["cluster"]] for cluster in clusters],
             capsize=3, error_kw={"linewidth": 0.8, "ecolor": "#555"})
    left.axhline(0, color="#2b2b2b", linewidth=0.8)
    left.set_xticks(positions)
    left.set_xticklabels([cluster["label"] for cluster in clusters], rotation=30, ha="right", fontsize=8)
    left.set_ylabel("difficulty score")
    left.set_title("difficulty by cluster (bars are 1 sd of the arms inside)")

    right.bar(positions, [cluster["loss_rate"]["mean"] for cluster in clusters],
              yerr=[cluster["loss_rate"]["sd"] for cluster in clusters],
              color=[colours[cluster["cluster"]] for cluster in clusters],
              capsize=3, error_kw={"linewidth": 0.8, "ecolor": "#555"})
    right.set_xticks(positions)
    right.set_xticklabels([cluster["label"] for cluster in clusters], rotation=30, ha="right", fontsize=8)
    right.set_ylabel("loss rate (%)")
    right.set_title("loss rate by cluster")

    for axis in (left, right):
        _style(axis)
    return _save(figure, path)


def figure_knn(summary, path):
    """Predicted against actual for the k-NN regression: the check that the parameters predict at all."""
    targets = summary["knn"]["targets"]

    figure, axes = plt.subplots(1, len(targets), figsize=(5.2 * len(targets), 4.6))
    axes = np.atleast_1d(axes)

    for axis, (name, result) in zip(axes, targets.items()):
        actual = np.asarray(result["actual"], dtype=float)
        predicted = np.asarray(result["predicted"], dtype=float)

        axis.scatter(actual, predicted, s=8, alpha=0.4, linewidths=0, color="#2e6f9e")
        limits = [min(actual.min(), predicted.min()), max(actual.max(), predicted.max())]
        axis.plot(limits, limits, color="#8c1d18", linewidth=1, linestyle="--")

        axis.set_xlabel(f"actual {name}")
        axis.set_ylabel(f"predicted {name}")
        axis.set_title(f"{name}: R² = {result['r2']:.3f}, MAE = {result['mae']:.2f}\n"
                       f"(predict-the-mean MAE = {result['baseline_mae']:.2f})", fontsize=9)
        _style(axis)

    figure.suptitle(f"k-NN regression from the parameters alone "
                    f"({summary['knn']['neighbours']} neighbours, "
                    f"{summary['knn']['folds']} fold cross validation)", fontsize=11)
    return _save(figure, path)


# --- entry point ------------------------------------------------------------


FIGURES = ("selection", "pca", "parameters", "outcomes", "difficulty", "knn")


def build_all(in_dir, out_dir):
    rows, summary = load(in_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = [
        figure_selection(summary, out_dir / "selection.png"),
        figure_pca(summary, out_dir / "pca.png"),
        figure_parameters(rows, summary, out_dir / "parameters.png"),
        figure_outcomes(rows, summary, out_dir / "outcomes.png"),
        figure_difficulty(summary, out_dir / "difficulty.png"),
        figure_knn(summary, out_dir / "knn.png"),
    ]
    return written


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in-dir", default=None,
                        help="where clusters.csv and cluster-summary.json are (default beside this)")
    parser.add_argument("--out-dir", default=None, help="where the PNGs go (default <in-dir>/figures)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    in_dir = pathlib.Path(args.in_dir) if args.in_dir else HERE
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else in_dir / "figures"

    for path in build_all(in_dir, out_dir):
        print(f"{path.name:<18} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
