#!/usr/bin/env python3
"""Finds the clusters of parameter settings that behave alike, and checks that they mean anything.

Reads arms.csv -- one row per configuration, as analyse.py writes it -- and produces

  * clusters.csv          arms.csv with a cluster label, a difficulty score and a difficulty rank added
  * cluster-summary.json  every number the report quotes: the k selection curves, each cluster's
                          centroid in original units, its difficulty rating, and the k-NN validation

K-means, not k-NN, for the clustering
-------------------------------------
k-NN is a supervised method: it has no clustering form, and there is nothing to supervise here because
nobody has labelled the configurations. So the grouping is K-means over the standardised space, and k-NN
comes back in the role it can actually fill -- k-NN *regression* from the eight parameters to the two
outcome metrics, cross validated. That is the check that separates "the parameters determine the
difficulty and the clusters are regions of a real surface" from "K-means partitioned a formless cloud,
as it always will".

The feature space
----------------
Eleven dimensions: the eight swept parameters and the two outcome metrics, standardised so that BHP in
[2, 20] and DENSITY_PROB in [0.45, 1] carry the same weight. Standardising is not a neutral act -- it
asserts that one standard deviation of density matters as much as one of fuel -- but every alternative
asserts something too, and this one at least does not depend on the units the settings happen to use.

Wind direction is encoded as MU times the unit heading vector, not as the heading alone. MU is the
contrast between downwind and everywhere else, so at MU = 0 the direction has no physical effect at all;
a raw (dx, dy) encoding would nevertheless place a still northerly arm far from a still southerly one and
invent a distinction the simulation does not make. Scaling by MU collapses them together as the wind
drops, which is what the model does. MU is kept as its own dimension because it sets the strength along
the ray as well as the direction of it.

Difficulty
----------
    difficulty = 0.5 * z(loss_rate) + 0.5 * z(-steps_survived)

Losing often and losing fast both count as hard, weighted equally. The equal weighting is a stated
convention, not something the data derives: it is written here so that a reader who disagrees can see
exactly what to change. The score is computed per arm and averaged over a cluster.

Run from the repository root:  python3 experiments/20260811_paramspace/cluster.py
"""

from __future__ import annotations

# python libraries

import argparse
import csv
import json
import math
import pathlib
import sys

import numpy as np
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.dummy import DummyRegressor
from sklearn.metrics import silhouette_score
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

# own python modules

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import design as design_module  # noqa: E402 - after the sys.path insert above

HERE = pathlib.Path(__file__).resolve().parent

# Fixed so the clustering is reproducible from the committed scripts alone. K-means is seeded by its
# initialisation, and an unseeded run would relabel the clusters -- and occasionally repartition them --
# every time the report was regenerated.
CLUSTER_SEED = 20260811

# the range of k searched. 2 is the smallest partition that is one, and past ~12 the clusters stop being
# things a reader can hold in mind, which is the whole point of producing them
K_RANGE = range(2, 13)

# k for the k-NN regression check. 5 of 2048 arms is a local neighbourhood in a 8 dimensional space
# without being so local that it just memorises.
KNN_NEIGHBOURS = 5

# the parameter columns, in feature vector order. Wind is not here: it enters as the two projected
# components below.
PARAMETER_COLUMNS = ("BHP", "MU", "BURNING_RATE", "FIRE_SPREAD_SPEED",
                     "DENSITY_PROB", "FUEL_BOTTOM_LIMIT", "FUEL_UPPER_LIMIT")

# the outcome columns, which join the parameters in the clustering space but are held out of the k-NN
# regression's inputs -- they are what it predicts
METRIC_COLUMNS = ("loss_rate", "steps_survived")

FEATURE_NAMES = (*PARAMETER_COLUMNS, "wind_x", "wind_y", *METRIC_COLUMNS)

# ordinal labels, applied hardest first. A cluster's name is its rank, not a claim about its contents.
DIFFICULTY_LABELS = ("severe", "hard", "moderate", "easy", "trivial")


# --- reading ----------------------------------------------------------------


def load_arms(path):
    with open(path) as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit(f"{path} has no rows: run analyse.py first")

    for row in rows:
        for name in ("BHP", "BURNING_RATE", "FIRE_SPREAD_SPEED",
                     "FUEL_BOTTOM_LIMIT", "FUEL_UPPER_LIMIT", "arm_id", "n", "lost"):
            row[name] = int(row[name])
        for name in ("MU", "DENSITY_PROB", "loss_rate", "steps_survived",
                     "loss_rate_low", "loss_rate_high", "burned_out_mean", "base_burning_mean"):
            row[name] = float(row[name])
        # null for an arm that never lost, which is exactly why it is not in the feature vector
        row["steps_to_loss"] = float(row["steps_to_loss"]) if row["steps_to_loss"] else None
    return rows


# --- the feature space ------------------------------------------------------


def wind_components(row, headings):
    """The wind as a vector of magnitude MU. See the module docstring for why it is scaled."""
    dx, dy = headings[row["WIND_DIRECTION"]]
    # the diagonals are (+-1, +-1), so normalise or a north easterly would be sqrt(2) times as windy
    length = (dx * dx + dy * dy) ** 0.5
    return row["MU"] * dx / length, row["MU"] * dy / length


def build_features(rows):
    """The 11 dimensional matrix the clustering runs over, one row per arm."""
    import config

    headings = config.WIND_HEADINGS

    matrix = []
    for row in rows:
        wind_x, wind_y = wind_components(row, headings)
        matrix.append([*(row[name] for name in PARAMETER_COLUMNS),
                       wind_x, wind_y,
                       *(row[name] for name in METRIC_COLUMNS)])
    return np.asarray(matrix, dtype=float)


# --- clustering -------------------------------------------------------------


def choose_k(scaled, k_range=K_RANGE, seed=CLUSTER_SEED):
    """Fit K-means across k and report both selection curves.

    Silhouette picks the k; inertia is reported alongside so that a reader can see the elbow and judge
    whether the silhouette's choice sits anywhere near it. Neither is a fact about the data -- there is
    no true number of clusters here -- so both curves go in the report rather than only the winner.
    """
    curve = []
    for k in k_range:
        model = KMeans(n_clusters=k, n_init=20, random_state=seed)
        labels = model.fit_predict(scaled)
        curve.append({
            "k": k,
            "inertia": float(model.inertia_),
            "silhouette": float(silhouette_score(scaled, labels)),
        })

    best = max(curve, key=lambda entry: entry["silhouette"])
    return best["k"], curve


def difficulty_scores(rows):
    """Per arm difficulty: high loss rate and short survival both count as hard, weighted equally."""
    loss = np.asarray([row["loss_rate"] for row in rows], dtype=float)
    survived = np.asarray([row["steps_survived"] for row in rows], dtype=float)

    def standardise(values):
        spread = values.std()
        return np.zeros_like(values) if spread == 0 else (values - values.mean()) / spread

    return 0.5 * standardise(loss) + 0.5 * standardise(-survived)


def _mean_interval(values):
    """95% t interval on the mean of a cluster's per-arm difficulty scores."""
    count = len(values)
    if count < 2:
        centre = float(values[0]) if count else 0.0
        return {"difficulty_low": centre, "difficulty_high": centre}
    # ddof=1: the sample standard deviation, since this is an interval on an estimate
    half = stats.t.ppf(0.975, count - 1) * float(values.std(ddof=1)) / math.sqrt(count)
    return {"difficulty_low": float(values.mean() - half),
            "difficulty_high": float(values.mean() + half)}


def tied_ranks(clusters):
    """Adjacent clusters whose difficulty intervals overlap, i.e. whose ordering is not evidence.

    K-means returns k clusters and sorting them returns an ordering whatever the data looks like. When
    two neighbouring clusters' 95% intervals overlap they are separated by their parameters, not by
    their difficulty, and a report that presents the rank as a difficulty tier is overstating it.
    """
    ties = []
    for first, second in zip(clusters, clusters[1:]):
        if first["difficulty_low"] <= second["difficulty_high"]:
            ties.append((first["rank"], second["rank"]))
    return ties


def summarise_clusters(rows, labels, scores, k):
    """One record per cluster: its size, its centroid in original units, and its difficulty."""
    clusters = []
    for label in range(k):
        members = [row for row, value in zip(rows, labels) if value == label]
        member_scores = scores[labels == label]

        # the centroid reported in the settings a reader would type into config.py, rather than in
        # standardised units, which are unreadable and depend on the rest of the design
        centre = {name: float(np.mean([row[name] for row in members]))
                  for name in PARAMETER_COLUMNS}

        # wind direction is categorical: a mean would be meaningless, so the distribution is given.
        # A cluster spread evenly over all eight is one the wind did not help define, which is itself
        # a result worth being able to read off.
        winds = {}
        for row in members:
            winds[row["WIND_DIRECTION"]] = winds.get(row["WIND_DIRECTION"], 0) + 1

        loss = np.asarray([row["loss_rate"] for row in members], dtype=float)
        survived = np.asarray([row["steps_survived"] for row in members], dtype=float)
        to_loss = [row["steps_to_loss"] for row in members if row["steps_to_loss"] is not None]

        clusters.append({
            "cluster": label,
            "arms": len(members),
            "share": 100.0 * len(members) / len(rows),
            "centroid": centre,
            "wind_directions": dict(sorted(winds.items(), key=lambda item: -item[1])),
            "loss_rate": {"mean": float(loss.mean()), "min": float(loss.min()),
                          "max": float(loss.max()), "sd": float(loss.std())},
            "steps_survived": {"mean": float(survived.mean()), "min": float(survived.min()),
                               "max": float(survived.max()), "sd": float(survived.std())},
            "steps_to_loss": {"mean": float(np.mean(to_loss)) if to_loss else None,
                              "arms_defined": len(to_loss)},
            "difficulty": float(member_scores.mean()),
            "difficulty_sd": float(member_scores.std()),
            # 95% interval on the cluster *mean*, so the report can say whether two clusters are
            # actually at different difficulties or merely at different ranks. K-means will always
            # return an ordering; that ordering is not evidence that the ends of it differ.
            **_mean_interval(member_scores),
            "always_lost_arms": int(sum(1 for row in members if row["loss_rate"] >= 100.0)),
            "never_lost_arms": int(sum(1 for row in members if row["loss_rate"] <= 0.0)),
        })

    # hardest first, and the ordinal label follows the rank
    clusters.sort(key=lambda entry: -entry["difficulty"])
    for rank, cluster in enumerate(clusters):
        cluster["rank"] = rank + 1
        cluster["label"] = _label_for(rank, len(clusters))
    return clusters


def _label_for(rank, total):
    """Spread the ordinal labels evenly over however many clusters there turned out to be.

    The endpoints are pinned: the hardest cluster is always 'severe' and the easiest always 'trivial',
    whatever k came out as. Interpolating without pinning them leaves the easiest cluster of a two
    cluster fit labelled 'moderate', which reads as a claim about its absolute difficulty rather than
    the ranking it actually is.
    """
    if total == 1:
        return DIFFICULTY_LABELS[0]
    index = round(rank * (len(DIFFICULTY_LABELS) - 1) / (total - 1))
    base = DIFFICULTY_LABELS[index]
    # past five clusters the labels have to repeat, so the rank disambiguates them
    return base if total <= len(DIFFICULTY_LABELS) else f"{base} {rank + 1}"


# --- the k-NN check ---------------------------------------------------------


def knn_validation(features, rows, neighbours=KNN_NEIGHBOURS, seed=CLUSTER_SEED):
    """Can the parameters alone predict the outcomes? k-NN regression, 5 fold cross validated.

    The inputs are the nine parameter dimensions only -- the two metric columns are held out, since they
    are what is being predicted. Scaling happens inside the cross validation pipeline rather than before
    it, so the folds' scaling is fitted on training data alone and no test fold leaks into it.

    Scored against a DummyRegressor that always predicts the training mean. R^2 is already relative to
    that baseline by definition, but reporting the baseline's MAE alongside is what makes the numbers
    mean something to a reader who does not want to convert an R^2 into an intuition.
    """
    inputs = features[:, :len(PARAMETER_COLUMNS) + 2]
    folds = KFold(n_splits=5, shuffle=True, random_state=seed)

    report = {"neighbours": neighbours, "folds": 5, "targets": {}}
    for index, name in enumerate(METRIC_COLUMNS):
        target = features[:, len(PARAMETER_COLUMNS) + 2 + index]

        model = make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=neighbours))
        predicted = cross_val_predict(model, inputs, target, cv=folds)

        baseline = cross_val_predict(DummyRegressor(strategy="mean"), inputs, target, cv=folds)

        report["targets"][name] = {
            "r2": float(1.0 - np.sum((target - predicted) ** 2) / np.sum((target - target.mean()) ** 2)),
            "mae": float(np.mean(np.abs(target - predicted))),
            "baseline_mae": float(np.mean(np.abs(target - baseline))),
            "sd": float(target.std()),
            # kept so figures.py can draw predicted against actual without refitting
            "predicted": [float(value) for value in predicted],
            "actual": [float(value) for value in target],
        }
    return report


# --- writing ----------------------------------------------------------------


def write_clusters_csv(rows, labels, scores, clusters, path):
    rank_of = {cluster["cluster"]: cluster["rank"] for cluster in clusters}
    label_of = {cluster["cluster"]: cluster["label"] for cluster in clusters}

    columns = [name for name in rows[0]] + ["cluster", "difficulty", "difficulty_rank",
                                            "difficulty_label"]
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row, label, score in zip(rows, labels, scores):
            writer.writerow({**{name: ("" if value is None else value)
                                for name, value in row.items()},
                             "cluster": int(label),
                             "difficulty": round(float(score), 4),
                             "difficulty_rank": rank_of[int(label)],
                             "difficulty_label": label_of[int(label)]})


# --- entry point ------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in-dir", default=None, help="where arms.csv is (default beside this script)")
    parser.add_argument("--out-dir", default=None, help="where the outputs go (default the same)")
    parser.add_argument("--k", type=int, default=0,
                        help="force a number of clusters instead of choosing by silhouette")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    in_dir = pathlib.Path(args.in_dir) if args.in_dir else HERE
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else in_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = load_arms(in_dir / "arms.csv")
    features = build_features(rows)

    scaler = StandardScaler().fit(features)
    scaled = scaler.transform(features)

    chosen, curve = choose_k(scaled)
    k = args.k or chosen

    model = KMeans(n_clusters=k, n_init=20, random_state=CLUSTER_SEED)
    labels = model.fit_predict(scaled)

    scores = difficulty_scores(rows)
    clusters = summarise_clusters(rows, labels, scores, k)

    # for the scatter figure. PCA on the same standardised space, so the picture is a projection of the
    # space the clustering actually ran in rather than of a different one drawn to look like it.
    projection = PCA(n_components=2, random_state=CLUSTER_SEED)
    projected = projection.fit_transform(scaled)

    validation = knn_validation(features, rows)

    write_clusters_csv(rows, labels, scores, clusters, out_dir / "clusters.csv")

    summary = {
        "arms": len(rows),
        "cluster_seed": CLUSTER_SEED,
        "features": list(FEATURE_NAMES),
        "k": k,
        "k_chosen_by_silhouette": chosen,
        "k_forced": bool(args.k),
        "selection_curve": curve,
        # None when --k forced a value outside the searched range, which is not on the curve
        "silhouette": next((entry["silhouette"] for entry in curve if entry["k"] == k), None),
        "difficulty_formula": "0.5 * z(loss_rate) + 0.5 * z(-steps_survived)",
        "clusters": clusters,
        # pairs of adjacent ranks that are not actually at different difficulties
        "tied_ranks": tied_ranks(clusters),
        "knn": validation,
        "pca": {
            "explained_variance_ratio": [float(value)
                                         for value in projection.explained_variance_ratio_],
            "components": [[float(value) for value in row] for row in projection.components_],
            "points": [[float(x), float(y)] for x, y in projected],
            "labels": [int(value) for value in labels],
        },
    }

    with open(out_dir / "cluster-summary.json", "w") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")

    # --- the tables ----------------------------------------------------------

    print(f"{len(rows)} arms, {len(FEATURE_NAMES)} features")
    print(f"clusters.csv -> {out_dir / 'clusters.csv'}")
    print(f"cluster-summary.json -> {out_dir / 'cluster-summary.json'}")
    print()

    print(f"{'k':>3} {'silhouette':>12} {'inertia':>12}")
    for entry in curve:
        mark = "  <- chosen" if entry["k"] == k else ""
        print(f"{entry['k']:>3} {entry['silhouette']:>12.4f} {entry['inertia']:>12.1f}{mark}")
    print()

    print(f"{'rank':>4} {'label':<12} {'arms':>5} {'diff':>7} {'loss %':>8} {'steps':>7}   centroid")
    for cluster in clusters:
        centre = cluster["centroid"]
        description = (f"BHP {centre['BHP']:.1f}  MU {centre['MU']:.2f}  "
                       f"burn {centre['BURNING_RATE']:.1f}  spread {centre['FIRE_SPREAD_SPEED']:.1f}  "
                       f"density {centre['DENSITY_PROB']:.2f}  "
                       f"fuel {centre['FUEL_BOTTOM_LIMIT']:.1f}-{centre['FUEL_UPPER_LIMIT']:.1f}")
        print(f"{cluster['rank']:>4} {cluster['label']:<12} {cluster['arms']:>5} "
              f"{cluster['difficulty']:>7.2f} {cluster['loss_rate']['mean']:>7.1f}% "
              f"{cluster['steps_survived']['mean']:>7.1f}   {description}")

    ties = summary["tied_ranks"]
    if ties:
        print()
        print("difficulty ties (95% intervals overlap; separated by parameters, not difficulty): "
              + ", ".join(f"{first} vs {second}" for first, second in ties))

    print()
    print(f"k-NN regression from the parameters alone ({KNN_NEIGHBOURS} neighbours, 5 fold CV):")
    for name, result in validation["targets"].items():
        print(f"  {name:<16} R2 = {result['r2']:>6.3f}   MAE = {result['mae']:>6.2f}   "
              f"(predict-the-mean MAE = {result['baseline_mae']:.2f})")

    ratio = summary["pca"]["explained_variance_ratio"]
    print()
    print(f"PCA: the 2 components drawn explain {100 * sum(ratio):.1f}% of the variance")

    return 0


if __name__ == "__main__":
    sys.exit(main())
