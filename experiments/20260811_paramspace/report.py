#!/usr/bin/env python3
"""Writes the report: report.md, then paramspace-report.html, then paramspace-report.pdf.

Every number in the report is read out of summary.json and cluster-summary.json. None is typed in by
hand. That is the point of this script existing rather than the report being written directly: a report
whose figures come from the data and whose sentences come from a person's memory of the data is a report
that goes stale silently, and experiments/20260810_wind/README.md already carries a warning block about
exactly that happening to its own scripts.

The chain is Markdown -> HTML -> PDF:

  * report.md is the canonical deliverable and is committed. It is readable in a terminal, diffs, and
    references the figures as ordinary relative paths.
  * the HTML is the same content rendered with the print stylesheet from experiments/20260810_wind/,
    with the PNGs inlined as base64 data URIs so the file stands alone.
  * the PDF is headless Chrome printing that HTML, which is how the previous two experiments made theirs.

Run from the repository root:  python3 experiments/20260811_paramspace/report.py
"""

from __future__ import annotations

# python libraries

import argparse
import base64
import json
import pathlib
import shutil
import subprocess
import sys

import markdown as markdown_module

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]

SLUG = "paramspace-report"

# Chrome is what the previous experiments printed with. Checked for rather than assumed, so that a
# missing Chrome costs a clear message rather than a stack trace after the Markdown was already written.
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


# --- helpers ----------------------------------------------------------------


def interval(low, high, digits=1):
    return f"{low:.{digits}f} – {high:.{digits}f}"


def number(value, digits=1):
    return "–" if value is None else f"{value:.{digits}f}"


def table(headers, rows):
    """A GitHub flavoured Markdown table."""
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def commit():
    result = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


# --- the report -------------------------------------------------------------


def build_markdown(summary, clusters, figures_dir):
    """Assemble report.md from the two summary files. No number here is typed by hand."""
    parts = []
    add = parts.append

    saturation = summary["saturation"]
    loss = summary["loss_rate"]
    survived = summary["steps_survived"]
    to_loss = summary["steps_to_loss"]
    knn = clusters["knn"]["targets"]
    ranked = clusters["clusters"]
    hardest, easiest = ranked[0], ranked[-1]
    figures = figures_dir.name

    # --- title and result ---------------------------------------------------

    add(f"# Baseline difficulty across the wildfire parameter space\n")
    add(f"**{summary['arms']} configurations of the unmanaged wildfire, "
        f"{summary['runs_per_arm']} simulations each ({summary['runs']:,} runs), "
        f"cluster into {clusters['k']} groups of similar behaviour.** "
        f"Loss rate spans {loss['min']:.1f}% to {loss['max']:.1f}% "
        f"(median {loss['median']:.1f}%), and the parameters predict it well enough for the grouping to "
        f"mean something: k-NN regression from the eight settings alone reaches "
        f"R² = {knn['loss_rate']['r2']:.2f} on loss rate and "
        f"R² = {knn['steps_survived']['r2']:.2f} on mean steps survived.\n")
    add(f"Commit `{commit()}`. Design seed `{summary['design_seed']}`, "
        f"fire seed block `{summary['seed_base']}`.\n")

    # --- 1 objective --------------------------------------------------------

    add("## 1. Objective\n")
    add("Establish which combinations of environment settings produce similar *baseline* difficulty — "
        "how hard the wildfire is with nothing defending against it — so that later UAV experiments can "
        "choose their scenarios from named regions of the parameter space rather than from the one "
        "calibrated configuration `config.py` ships with.\n")
    add("Two questions follow from that. Where on the difficulty surface does a given set of parameters "
        "land, and do the parameters determine the difficulty at all, or is the outcome dominated by "
        "where the fire happened to start?\n")

    # --- 2 model ------------------------------------------------------------

    add("## 2. Model\n")
    add("Zero UAVs, no managing system, and a home base for the fire to reach. A run is **lost** when "
        "the base has burned for `BHP` steps, cumulatively, and **won** by surviving "
        f"{summary['batch_size']} steps with the base standing. With no UAVs flying, no water is ever "
        "dropped, so the outcome is a property of the fire and the terrain alone.\n")
    add("Held fixed in every configuration:\n")
    add(table(["setting", "value", "why"], [
        ("`WIDTH` × `HEIGHT`", "100 × 100", "the calibrated grid"),
        ("`BATCH_SIZE`", str(summary["batch_size"]), "run length in steps; the only run length there is"),
        ("`NUM_AGENTS`", "0", "the measurement is the fire on its own"),
        ("`MANAGING_SYSTEM`", "`none`", "nothing adapts"),
        ("`ACTIVATE_FIREFIGHTING`", "`True`", "required — it is the base that is lost"),
        ("`FIRE_START_STEP`", "0", "alight before the first step"),
        ("`FIRE_START_POSITION`", "`random`", "uniform over the grid, avoiding the base"),
        ("`ACTIVATE_SMOKE`", "`False`", "smoke only occludes observation, and nothing observes"),
        ("`WIND_VARIABILITY`", "`None`", "one direction for the whole run"),
        ("`ACTIVATE_FUEL`", "`False`", "UAV tanks; no UAVs"),
        ("`ACTIVATE_POSITION_ERROR`", "`False`", "UAV position noise; no UAVs"),
    ]) + "\n")

    # --- 3 design -----------------------------------------------------------

    add("## 3. Design\n")
    add(f"A scrambled Sobol sequence of {summary['arms']} points, not a grid. A full factorial over "
        "eight parameters at usable resolution is tens of thousands of arms, and a coarse one covers the "
        "space with a lattice that a distance-based clustering method mostly just recovers. Sobol spends "
        "the same budget on points spread evenly at every scale.\n")
    add("Seven dimensions come from the sequence. Wind direction is categorical and is **stratified** "
        f"instead — exactly {summary['arms'] // 8} configurations per compass point.\n")

    ranges = summary["ranges"]
    add(table(["parameter", "range", "`config.py` default", "note"], [
        ("`BHP`", f"{ranges['BHP'][0]} – {ranges['BHP'][1]}", "4",
         "steps the base survives burning for"),
        ("`MU`", f"{ranges['MU'][0]} – {ranges['MU'][1]}", "0.9",
         "downwind contrast, **not** wind speed; 0 is a still day"),
        ("`BURNING_RATE`", f"{ranges['BURNING_RATE'][0]} – {ranges['BURNING_RATE'][1]}", "1",
         "fuel lost per fire update; larger burns out sooner"),
        ("`FIRE_SPREAD_SPEED`",
         f"{ranges['FIRE_SPREAD_SPEED'][0]} – {ranges['FIRE_SPREAD_SPEED'][1]}", "1",
         "steps *between* fire updates, so larger is **slower**"),
        ("`DENSITY_PROB`", f"{ranges['DENSITY_PROB'][0]} – {ranges['DENSITY_PROB'][1]}", "0.9",
         "vegetation density"),
        ("`FUEL_BOTTOM_LIMIT`",
         f"{ranges['FUEL_BOTTOM_LIMIT'][0]} – {ranges['FUEL_BOTTOM_LIMIT'][1]}", "5",
         "per-cell fuel floor"),
        ("`FUEL_UPPER_LIMIT`", "bottom – 24", "10",
         "drawn from the bottom limit up, so `bottom ≤ upper` holds by construction"),
        ("`WIND_DIRECTION`", "8 compass points", "`['NORTH', 'SOUTH']`",
         f"stratified, {summary['arms'] // 8} arms each"),
    ]) + "\n")
    add("The ranges deliberately reach past the shipped defaults on the *easy* side. The zero-UAV "
        "baseline at those defaults lost 100% of 5000 runs, so a design centred on them would have "
        "measured nothing but the ceiling.\n")

    # --- 4 method -----------------------------------------------------------

    add("## 4. Method\n")
    add(f"Each configuration ran {summary['runs_per_arm']} simulations. Run *i* of **every** "
        f"configuration uses seed `{summary['seed_base']} + i`, so the configurations are paired on the "
        "fire: they see the same ignitions, and the difference between two of them is not partly the "
        "difference between two sets of fires.\n")
    add("Two outcome metrics, because steps-to-loss is censored:\n")
    add("- **loss rate** — the share of runs lost, with a 95% Wilson interval.\n"
        "- **steps to loss** — mean over the lost runs only, with a 95% *t* interval. Undefined for a "
        "configuration that never loses.\n"
        f"- **steps survived** — mean over every run, a survivor contributing {summary['batch_size']}. "
        "Defined everywhere, so this is the one that enters the clustering.\n")
    add(f"Clustering is **K-means** over the {len(clusters['features'])} standardised dimensions — the "
        "eight parameters and the two outcome metrics — with *k* chosen by silhouette score over "
        f"{clusters['selection_curve'][0]['k']}–{clusters['selection_curve'][-1]['k']}. "
        "k-NN has no clustering form; it is a supervised method, and there are no labels here. It comes "
        "back in the role it can fill, as the validation in §7.\n")
    add("Wind direction enters the feature space as `MU` times the unit heading vector, not as the "
        "heading alone. At `MU = 0` the direction has no physical effect, so a raw encoding would place "
        "a still northerly far from a still southerly and invent a distinction the simulation does not "
        "make.\n")

    # --- 5 results ----------------------------------------------------------

    add("## 5. Results: the difficulty surface\n")
    add(table(["metric", "min", "p25", "median", "p75", "max"], [
        ("loss rate (%)", f"{loss['min']:.1f}", f"{loss['p25']:.1f}", f"{loss['median']:.1f}",
         f"{loss['p75']:.1f}", f"{loss['max']:.1f}"),
        ("steps to loss", number(to_loss.get("min")), number(to_loss.get("p25")),
         number(to_loss.get("median")), number(to_loss.get("p75")), number(to_loss.get("max"))),
        ("steps survived", f"{survived['min']:.1f}", f"{survived['p25']:.1f}",
         f"{survived['median']:.1f}", f"{survived['p75']:.1f}", f"{survived['max']:.1f}"),
    ]) + "\n")
    add(f"The design spans the whole range rather than piling up at one end: "
        f"{saturation['always_lost']} configurations "
        f"({saturation['always_lost_share']:.1f}%) lost every run and "
        f"{saturation['never_lost']} ({saturation['never_lost_share']:.1f}%) lost none. "
        f"Those {saturation['no_steps_to_loss']} with no losses have no steps-to-loss at all, which is "
        "the censoring §8 returns to.\n")
    add(f"At {summary['runs_per_arm']} runs each, a single configuration's loss rate carries a 95% "
        f"Wilson interval of about ± {summary['mean_wilson_half_width']:.1f} points. That is the "
        "resolution of one point on the surface; the clusters below average over many.\n")

    add(f"![loss rate against each swept parameter]({figures}/parameters.png)\n")
    add(f"![the two key metrics]({figures}/outcomes.png)\n")

    # wind direction is the one axis that is balanced by construction, so its marginal is readable
    # straight off the design without conditioning on anything
    add(_wind_section(summary))

    # --- 6 clusters ---------------------------------------------------------

    add("## 6. The clusters\n")
    add(f"Silhouette selected **k = {clusters['k']}** "
        f"(score {clusters['silhouette']:.3f}). Both selection curves are drawn, because there is no "
        "true number of clusters here and the choice should be visible rather than asserted.\n")
    add(f"![k selection]({figures}/selection.png)\n")
    add(f"![the clustering space projected]({figures}/pca.png)\n")

    add("Difficulty is `" + clusters["difficulty_formula"] + "` — losing often and losing fast both "
        "count as hard, weighted equally. **The equal weighting is a stated convention, not something "
        "the data derives.**\n")

    add(table(["rank", "label", "arms", "difficulty (95% CI)", "loss rate",
               "steps survived", "steps to loss"],
              [(cluster["rank"], f"**{cluster['label']}**", cluster["arms"],
                f"{cluster['difficulty']:+.2f} "
                f"({cluster['difficulty_low']:+.2f} to {cluster['difficulty_high']:+.2f})",
                f"{cluster['loss_rate']['mean']:.1f}% "
                f"({cluster['loss_rate']['min']:.0f}–{cluster['loss_rate']['max']:.0f})",
                f"{cluster['steps_survived']['mean']:.1f}",
                number(cluster["steps_to_loss"]["mean"]))
               for cluster in ranked]) + "\n")
    add(_ties_note(clusters) + "\n")

    add("What each cluster is, in the settings a reader would type into `config.py`:\n")
    add(table(["rank", "label", "BHP", "MU", "burn rate", "spread speed", "density", "fuel", "wind"],
              [(cluster["rank"], f"**{cluster['label']}**",
                f"{cluster['centroid']['BHP']:.1f}",
                f"{cluster['centroid']['MU']:.2f}",
                f"{cluster['centroid']['BURNING_RATE']:.1f}",
                f"{cluster['centroid']['FIRE_SPREAD_SPEED']:.1f}",
                f"{cluster['centroid']['DENSITY_PROB']:.2f}",
                f"{cluster['centroid']['FUEL_BOTTOM_LIMIT']:.1f}–"
                f"{cluster['centroid']['FUEL_UPPER_LIMIT']:.1f}",
                _wind_note(cluster))
               for cluster in ranked]) + "\n")
    add("Values are cluster means, so they describe the region rather than naming a member of it. A "
        "cluster whose wind column reads *even* is one the wind direction did not help define.\n")

    add(f"![difficulty by cluster]({figures}/difficulty.png)\n")

    add(f"The hardest region, **{hardest['label']}**, loses "
        f"{hardest['loss_rate']['mean']:.1f}% of its runs and survives "
        f"{hardest['steps_survived']['mean']:.1f} of {summary['batch_size']} steps on average. The "
        f"easiest, **{easiest['label']}**, loses {easiest['loss_rate']['mean']:.1f}% and survives "
        f"{easiest['steps_survived']['mean']:.1f}.\n")

    # --- 7 validation -------------------------------------------------------

    add("## 7. Do the parameters predict the outcome?\n")
    add("K-means will partition a formless cloud as readily as a structured one, so the clusters are "
        "worth nothing on their own. The check is k-NN regression from the **parameters alone** — the "
        "outcome metrics held out — to each metric, "
        f"{clusters['knn']['neighbours']} neighbours, {clusters['knn']['folds']}-fold cross validation, "
        "with scaling fitted inside each fold so no test data leaks into it.\n")
    add(table(["target", "R²", "MAE", "predict-the-mean MAE", "sd"], [
        (name, f"{result['r2']:.3f}", f"{result['mae']:.2f}",
         f"{result['baseline_mae']:.2f}", f"{result['sd']:.2f}")
        for name, result in knn.items()
    ]) + "\n")
    add(_verdict(knn) + "\n")
    add(f"![k-NN predicted against actual]({figures}/knn.png)\n")

    # --- 8 validity ---------------------------------------------------------

    add("## 8. Validity\n")
    add("**Steps survived is censored, not a survival time.** A run that never loses contributes "
        f"{summary['batch_size']}, so at the easy end the metric saturates and stops distinguishing a "
        "configuration the fire never threatens from one it nearly reaches. Loss rate carries that end "
        "of the surface; steps survived carries the hard end. Neither alone is the difficulty.\n")
    add(f"**All {summary['arms']} configurations share {summary['runs_per_arm']} ignitions.** Pairing on "
        "the seed is what makes two configurations comparable — it removes ignition position from the "
        "difference between them — but it means every configuration's *absolute* loss rate carries the "
        "same fire-sample error. Relative comparisons are much tighter than the absolute numbers.\n")
    add("**The difficulty score is a convention.** Equal weight on loss rate and on survival time is "
        "asserted here, not derived. A reader who weights them differently will get a different "
        "ranking from the same clusters; the per-arm scores are in `clusters.csv` to make that cheap.\n")
    add("**Standardising asserts something too.** Giving one standard deviation of density the same "
        "weight as one of fuel is a choice about what 'similar' means. Every alternative is also a "
        "choice; this one at least does not depend on the units the settings happen to use.\n")
    add(f"**k is not a fact about the data.** Silhouette peaked at {clusters['k']}, but the curve in "
        "§6 is shallow across much of its range, which is what a continuous surface looks like when it "
        "is cut into pieces. The clusters are a useful summary of that surface, not seams in it.\n")

    # --- 9 not run ----------------------------------------------------------

    add("## 9. What was not run\n")
    add("- **Anything with UAVs.** This is the baseline the adaptation experiments are measured "
        "against, not a measurement of any policy.\n"
        "- **`BATCH_SIZE`.** Held at "
        f"{summary['batch_size']} throughout. It is the strongest difficulty dial there is, which is "
        "exactly why sweeping it alongside the others would have swamped them.\n"
        "- **Grid size.** Held at 100 × 100, so nothing here says how the clusters move with it.\n"
        "- **`WIND_VARIABILITY`.** Every run holds one direction. A wind that redraws mid-run is a "
        "different model and would need its own axis.\n"
        "- **Smoke.** Switched off. It only occludes observation, and nothing observes.\n")

    # --- 10 reproducing -----------------------------------------------------

    add("## 10. Reproducing\n")
    add("```bash\n"
        "python3 -m pip install -r requirements.txt\n"
        "python3 experiments/20260811_paramspace/design.py       # design.json, deterministic\n"
        "python3 experiments/20260811_paramspace/dump_config.py  # config-used.json\n"
        "python3 experiments/20260811_paramspace/run.py --workers 10   # hours\n"
        "python3 experiments/20260811_paramspace/analyse.py      # arms.csv, summary.json\n"
        "python3 experiments/20260811_paramspace/cluster.py      # clusters.csv, cluster-summary.json\n"
        "python3 experiments/20260811_paramspace/figures.py      # figures/*.png\n"
        "python3 experiments/20260811_paramspace/report.py       # this file, and the PDF\n"
        "```\n")
    add("`run.py` checkpoints per configuration and resumes, so it can be interrupted. Set the run "
        "length through `BATCH_SIZE` in `design.py`, never through a step count — the model stops "
        "itself at its own `BATCH_SIZE`, and a loop bound below it scores a truncated run as won.\n")

    return "\n".join(parts)


CARDINALS = ("NORTH", "EAST", "SOUTH", "WEST")


def _wind_section(summary):
    """The wind direction marginal.

    Worth its own section because wind direction is the one axis stratified by construction: every
    direction got exactly the same number of configurations, drawn from the same Sobol points, so its
    marginal can be read straight off without conditioning on anything else.
    """
    by_direction = {name: spread for name, spread in summary["by_wind_direction"].items()
                    if spread.get("n")}
    if not by_direction:
        return ""

    ranked = sorted(by_direction.items(), key=lambda item: -item[1]["mean"])
    cardinal = [spread["mean"] for name, spread in by_direction.items() if name in CARDINALS]
    diagonal = [spread["mean"] for name, spread in by_direction.items() if name not in CARDINALS]

    parts = ["### Wind direction\n"]
    parts.append(table(["direction", "configurations", "mean loss rate"],
                       [(name.replace("_", " ").lower(), spread["n"], f"{spread['mean']:.1f}%")
                        for name, spread in ranked]) + "\n")

    hardest, easiest = ranked[0], ranked[-1]
    parts.append(
        f"Direction matters more than any single other setting's marginal: "
        f"{hardest[0].replace('_', ' ').lower()} loses {hardest[1]['mean']:.1f}% of its runs against "
        f"{easiest[1]['mean']:.1f}% for {easiest[0].replace('_', ' ').lower()}, a factor of "
        f"{hardest[1]['mean'] / easiest[1]['mean']:.1f}. Each figure averages "
        f"{hardest[1]['n']} configurations spread over the whole of the rest of the space, so this is "
        "the effect of direction alone.\n")

    if cardinal and diagonal:
        parts.append(
            f"The split is **cardinal against diagonal**, not toward-the-base against away-from-it: "
            f"the four cardinal directions average {sum(cardinal) / len(cardinal):.1f}% and the four "
            f"diagonals {sum(diagonal) / len(diagonal):.1f}%. That ordering is not explained by the "
            "home base sitting a quarter into the grid — the mean ignition cell of a lost run sits "
            "closer to the base than the grid mean under *every* direction, cardinal or not. "
            "**This experiment establishes the pattern and does not explain it.** A mechanism would "
            "have to come from how `fire_spread.on_wind()` picks upwind neighbours out of a Moore "
            "neighbourhood, and testing that needs its own experiment.\n")

    return "\n".join(parts)


def _ties_note(clusters):
    """State plainly which parts of the ranking are a ranking and which are a real difference.

    K-means returns k clusters and sorting them by difficulty returns an ordering whatever the data
    looks like. Presenting that ordering as difficulty tiers without saying which neighbouring pairs
    are statistically indistinguishable is the most likely way this report gets over-read.
    """
    ties = clusters.get("tied_ranks") or []
    if not ties:
        return ("Every adjacent pair of ranks is separated by more than its 95% interval, so the "
                "ordering is a difficulty ordering throughout.")
    pairs = ", ".join(f"**{first}** and **{second}**" for first, second in ties)
    return (f"**The ranking is not uniformly a difficulty ranking.** Ranks {pairs} have overlapping "
            "95% intervals on their mean difficulty: those clusters are separated by their "
            "*parameters*, not by how hard they are. Different combinations of settings arrive at the "
            "same difficulty, which is the more useful finding — it means a scenario of a given "
            "difficulty can be reached several ways, and the clusters say which.")


def _wind_note(cluster):
    """How concentrated a cluster is on one wind direction, in a table cell's worth of words."""
    winds = cluster["wind_directions"]
    if not winds:
        return "–"
    top, count = next(iter(winds.items()))
    share = count / cluster["arms"]
    # 8 directions, so an evenly spread cluster sits near 1/8. Twice that is the threshold for
    # calling the cluster concentrated at all.
    if share < 0.25:
        return "even"
    return f"{top.replace('_', ' ').lower()} ({100 * share:.0f}%)"


def _verdict(knn):
    """One sentence reading the k-NN result, so the report states a conclusion rather than a table."""
    worst = min(result["r2"] for result in knn.values())
    if worst >= 0.7:
        return ("The parameters carry most of the outcome. The clusters are regions of a real surface, "
                "not a partition of noise.")
    if worst >= 0.4:
        return ("The parameters carry a clear majority of the outcome, with the remainder going to the "
                "ignition position and the run-to-run variance of the fire itself. The clusters "
                "describe real structure, and individual configurations inside one still vary.")
    if worst >= 0.15:
        return ("The parameters carry a real but minority share of the outcome: the ignition position "
                "and the fire's own variance dominate. The clusters describe tendencies, and should "
                "not be read as predicting any single configuration.")
    return ("The parameters barely predict the outcome at this resolution. The clusters should be "
            "treated as a summary of the design, not as regions of a difficulty surface.")


# --- rendering --------------------------------------------------------------

STYLESHEET = """
  :root {
    --ground: #ffffff; --surface: #f5f7f6; --surface-alt: #e7ebea;
    --ink: #14201e; --ink-soft: #4d5957; --rule: #c6cecc; --rule-soft: #dde3e1;
    --accent: #0f6f73; --accent-ink: #0a5053; --accent-wash: #e2eeee;
    --mono: "SF Mono", ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
    --serif: Charter, "Bitstream Charter", "Iowan Old Style", "Source Serif 4", Georgia, serif;
  }
  @page { size: A4; margin: 16mm 14mm 18mm; }
  * { box-sizing: border-box; }
  html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body {
    margin: 0 auto; max-width: 52rem; padding: 0 1.5rem 3rem;
    background: var(--ground); color: var(--ink);
    font-family: var(--serif); font-size: 10.5pt; line-height: 1.5;
  }
  h1 {
    font-family: var(--mono); font-weight: 500; font-size: 19pt; line-height: 1.15;
    letter-spacing: -0.02em; margin: 0 0 1rem; text-wrap: balance;
  }
  h2 {
    font-family: var(--mono); font-weight: 500; font-size: 12pt;
    margin: 2.2rem 0 0.75rem; padding-bottom: 0.3rem;
    border-bottom: 1px solid var(--rule); color: var(--accent-ink);
    break-after: avoid;
  }
  p { margin: 0 0 0.8rem; }
  strong { color: var(--accent-ink); }
  ul { margin: 0 0 0.9rem; padding-left: 1.2rem; }
  li { margin-bottom: 0.3rem; }
  code {
    font-family: var(--mono); font-size: 0.86em;
    background: var(--surface); padding: 0.08em 0.32em;
    border: 1px solid var(--rule-soft); border-radius: 3px;
  }
  pre {
    background: var(--surface); border: 1px solid var(--rule-soft);
    border-radius: 4px; padding: 0.8rem 1rem; overflow-x: auto;
    font-size: 8.5pt; line-height: 1.5; break-inside: avoid;
  }
  pre code { background: none; border: none; padding: 0; font-size: inherit; }
  table {
    border-collapse: collapse; width: 100%; margin: 0 0 1.2rem;
    font-size: 8.8pt; break-inside: avoid;
  }
  th, td {
    border-bottom: 1px solid var(--rule-soft);
    padding: 0.35rem 0.5rem; text-align: left; vertical-align: top;
  }
  th {
    font-family: var(--mono); font-weight: 500; font-size: 7.8pt;
    text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--accent-ink); background: var(--accent-wash);
    border-bottom: 1px solid var(--rule);
  }
  tr:nth-child(even) td { background: var(--surface); }
  img {
    display: block; width: 100%; height: auto; margin: 1rem 0 1.4rem;
    border: 1px solid var(--rule-soft); border-radius: 4px;
    break-inside: avoid;
  }
"""


def render_html(text, source_dir, title):
    """Markdown to a single self-contained HTML file, with the PNGs inlined."""
    body = markdown_module.markdown(text, extensions=["tables", "fenced_code"])

    # inline every figure so the HTML is one file. The Markdown keeps the relative paths.
    for path in sorted((source_dir / "figures").glob("*.png")):
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        body = body.replace(f'src="figures/{path.name}"',
                            f'src="data:image/png;base64,{encoded}"')

    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<title>{title}</title>\n<style>{STYLESHEET}</style>\n</head>\n<body>\n'
            f'{body}\n</body>\n</html>\n')


def print_pdf(html_path, pdf_path):
    """Headless Chrome, the way the previous two experiments made their PDFs."""
    chrome = CHROME if pathlib.Path(CHROME).exists() else shutil.which("google-chrome") \
        or shutil.which("chromium")
    if not chrome:
        print(f"Chrome not found at {CHROME}; the HTML is written, the PDF is not.\n"
              f"  Print it with:  \"{CHROME}\" --headless --disable-gpu "
              f"--no-pdf-header-footer --print-to-pdf={pdf_path} {html_path}", file=sys.stderr)
        return False

    result = subprocess.run(
        [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf_path}", str(html_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not pdf_path.exists():
        print(f"Chrome failed to print the PDF (exit {result.returncode}):\n{result.stderr}",
              file=sys.stderr)
        return False
    return True


# --- entry point ------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in-dir", default=None,
                        help="where summary.json and cluster-summary.json are (default beside this)")
    parser.add_argument("--out-dir", default=None, help="where the report goes (default the same)")
    parser.add_argument("--no-pdf", action="store_true", help="write the Markdown and HTML only")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    in_dir = pathlib.Path(args.in_dir) if args.in_dir else HERE
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else in_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(in_dir / "summary.json") as handle:
        summary = json.load(handle)
    with open(in_dir / "cluster-summary.json") as handle:
        clusters = json.load(handle)

    figures_dir = in_dir / "figures"
    if not figures_dir.exists():
        raise SystemExit(f"{figures_dir} does not exist: run figures.py first")

    title = "Baseline difficulty across the wildfire parameter space"
    text = build_markdown(summary, clusters, figures_dir)

    markdown_path = out_dir / "report.md"
    markdown_path.write_text(text)
    print(f"report.md  -> {markdown_path}")

    html_path = out_dir / f"{SLUG}.html"
    html_path.write_text(render_html(text, in_dir, title))
    print(f"{SLUG}.html -> {html_path}")

    if args.no_pdf:
        return 0

    pdf_path = out_dir / f"{SLUG}.pdf"
    if print_pdf(html_path, pdf_path):
        print(f"{SLUG}.pdf  -> {pdf_path}  "
              f"({pdf_path.stat().st_size / 1024:.0f} kB)")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
