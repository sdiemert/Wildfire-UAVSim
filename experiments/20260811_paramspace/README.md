# Baseline difficulty across the wildfire parameter space

**Result: 2048 configurations of the unmanaged wildfire, 100 simulations each (204,800 runs), cluster
into 6 groups of similar behaviour. Loss rate spans 0% – 100% (median 28%), and the parameters predict
it — k-NN regression from the eight settings alone reaches R² = 0.69 on loss rate and R² = 0.72 on mean
steps survived.**

Run at commit `bad2d97`. The write-up is [`report.md`](report.md) and
[`paramspace-report.pdf`](paramspace-report.pdf).

Sweeps eight environment parameters over 2048 configurations with **zero UAVs**, 100 simulations each,
then clusters the (parameters + outcomes) space to find groups of settings that behave alike and rates
them by difficulty.

## Headline findings

| | |
|---|---|
| Loss rate range | 0% – 100%, median 28%, p25 11%, p75 51% |
| Saturation | only 17 configurations (0.8%) always lost, 167 (8.2%) never lost |
| Resolution | ± 7.1 points, mean 95% Wilson half-width per configuration |
| Clusters | k = 6 by silhouette (0.173) |
| Hardest cluster | 346 arms, 80.6% lost, survives 62.7 of 100 steps |
| Easiest cluster | 274 arms, 14.1% lost, survives 95.3 |
| k-NN validation | R² = 0.685 (loss rate), 0.723 (steps survived); MAE 10.7 and 4.5 points |

Three things worth knowing before using the clusters:

**The ranking is not uniformly a difficulty ranking.** Ranks 2/3 and 5/6 have overlapping 95% intervals
on their mean difficulty. They are separated by their *parameters*, not by how hard they are — different
combinations of settings reach the same difficulty, which is the more useful finding: a scenario of a
given difficulty can be reached several ways, and the clusters say which.

**Stronger wind makes runs easier, not harder.** Loss rate falls steadily with `MU`. This matches the
note already in `config.py` that stronger wind moves the win rate the counter-intuitive way — the wind
focuses the fire into a narrow downwind ray instead of spreading it in all directions.

**Wind direction is the strongest single marginal, and the split is cardinal against diagonal.** North
loses 56.7% against north-east's 17.5%, a factor of 3.2. The four cardinals average 43.2% and the four
diagonals 24.5%. This is *not* explained by the base sitting a quarter into the grid: the mean ignition
cell of a lost run sits closer to the base under every direction. **The experiment establishes the
pattern and does not explain it** — a mechanism would have to come from how `fire_spread.on_wind()`
picks upwind neighbours out of a Moore neighbourhood, and that needs its own experiment.

The point is to replace guesswork in later UAV experiments. Right now there is one calibrated
configuration and one wind axis measured around it; an experiment that wants a *hard* scenario or an
*easy* one has nothing to pick from. This produces named, difficulty-ranked regions of the parameter
space, plus the evidence (k-NN regression) that the parameters predict the outcome well enough for those
regions to mean anything.

## The question about method, answered up front

**k-NN is a supervised method and has no clustering form.** Nothing here is labelled, so there is nothing
to supervise. The grouping is **K-means** over the standardised feature space, with *k* chosen by
silhouette score. k-NN comes back in the role it can actually fill: **k-NN regression** from the eight
parameters to the two outcome metrics, cross validated, as the check that separates *"these are regions
of a real difficulty surface"* from *"K-means partitioned a formless cloud, as it always will"*.

## Design

A **scrambled Sobol** space-filling sample of 2048 points, not a grid. A full factorial over eight
parameters at usable resolution is tens of thousands of arms; a coarse one covers the space with a
lattice that a distance-based method mostly just recovers.

| Parameter | Range | `config.py` default | Note |
|---|---|---|---|
| `BHP` | 2 – 20 | 4 ⚠ | steps the base survives burning for |
| `MU` | 0.0 – 0.95 | 0.9 ⚠ | downwind contrast, **not** wind speed; 0 is a still day |
| `BURNING_RATE` | 1 – 4 | 1 ⚠ | fuel lost per fire update; larger burns out sooner |
| `FIRE_SPREAD_SPEED` | 1 – 6 | 1 ⚠ | steps *between* fire updates, so larger is **slower** |
| `DENSITY_PROB` | 0.45 – 1.0 | 0.9 ⚠ | vegetation density |
| `FUEL_BOTTOM_LIMIT` | 1 – 12 | 5 ⚠ | per-cell fuel floor |
| `FUEL_UPPER_LIMIT` | bottom – 24 | 10 ⚠ | drawn from the bottom limit up |
| `WIND_DIRECTION` | 8 compass points | `['NORTH','SOUTH']` ⚠ | stratified, exactly 256 arms each |

Seven dimensions come from the Sobol sequence. Wind direction is categorical, so it is stratified
instead. `FUEL_UPPER_LIMIT` is drawn from `FUEL_BOTTOM_LIMIT` upwards, so `bottom ≤ upper` holds **by
construction** rather than by rejecting half a square.

The ranges deliberately reach past the shipped defaults on the *easy* side. The
[zero-UAV baseline](../20260810_baseline/) at those defaults lost **100% of 5000 runs**, so a design
centred on them would have measured nothing but the ceiling. It worked: only 0.8% of configurations
landed on the ceiling and 8.2% on the floor, leaving 91% of the budget measuring somewhere the surface
actually varies.

Held fixed in every arm (⚠ marks a departure from `config.py`):

| Setting | Value | Why |
|---|---|---|
| `WIDTH` × `HEIGHT` | 100 × 100 | the calibrated grid |
| `BATCH_SIZE` | 100 | run length in steps; the only run length there is |
| `NUM_AGENTS` | 0 ⚠ | the measurement is the fire on its own |
| `MANAGING_SYSTEM` | `none` ⚠ | nothing adapts |
| `ACTIVATE_FIREFIGHTING` | `True` | **required** — it is the base that is lost |
| `FIRE_START_STEP` | 0 ⚠ | alight before the first step |
| `FIRE_START_POSITION` | `random` | uniform over the grid, avoiding the base |
| `ACTIVATE_SMOKE` | `False` ⚠ | smoke only occludes observation, and nothing observes |
| `WIND_VARIABILITY` | `None` ⚠ | one direction for the whole run |
| `ACTIVATE_FUEL` | `False` ⚠ | UAV tanks; no UAVs |
| `ACTIVATE_POSITION_ERROR` | `False` ⚠ | UAV position noise; no UAVs |

## Metrics

- **loss rate** — share of runs lost, 95% **Wilson** interval. `wilson()` is imported from
  `tools/sweep.py`, never reimplemented, so this experiment and the sweep tool cannot disagree about
  what a 95% interval is.
- **steps to loss** — mean over the *lost* runs only, 95% *t* interval. **Undefined** for a
  configuration that never loses.
- **steps survived** — mean over *every* run, a survivor contributing `BATCH_SIZE`. Defined everywhere,
  so this is the one that enters the clustering feature vector.

Both step metrics exist because steps-to-loss is **censored**: a run that survives has no loss step. At
the easy end `steps_survived` saturates at 100 and stops distinguishing anything, so loss rate carries
that end of the surface and steps carries the hard end. Neither alone is the difficulty.

## Method notes worth knowing before reading any number

**Arms are paired on the fire.** Run *i* of *every* configuration uses seed `7000000 + i`, following the
convention in `tools/sweep.py`. This removes ignition position from the difference between two
configurations — which is what the clustering is about — at the cost that all 2048 configurations share
the same 100 ignitions, so every *absolute* loss rate carries the same fire-sample error. Relative
comparisons are much tighter than absolute ones.

**Wind is encoded as `MU` × the unit heading vector,** not as the heading alone. At `MU = 0` the
direction has no physical effect, so a raw `(dx, dy)` encoding would place a still northerly far from a
still southerly and invent a distinction the simulation does not make.

**Difficulty is `0.5·z(loss_rate) + 0.5·z(−steps_survived)`.** Losing often and losing fast both count as
hard, weighted equally. The equal weighting is a **stated convention, not something the data derives**;
per-arm scores are in `clusters.csv` so a different weighting is cheap to apply.

## Why the runner does not use `tools/sweep.py`

`tools/sweep.py scan` runs each arm in its own `headless.py` subprocess, because `apply_overrides()` and
`seed_simulation()` mutate the global `config` module and arms sharing a process would leak settings into
one another. That is the right trade at 73 arms; at 2048 it is an hour of interpreter and mesa startup,
and `scan` can only express a cartesian product anyway.

`run.py` goes one level down instead. `sim/cli/batch.run_batch()` already takes a **heterogeneous** list
of `RunConfig`, and `sim/cli/runner.run_simulation()` applies each config's own overrides and seed inside
whichever worker picks it up — the same isolation, without the per-arm cost.

> **The invariant this rests on:** workers are reused and `apply_overrides()` resets nothing, so a
> setting one arm overrides and another does not would keep the first arm's value. **Every `RunConfig`
> must carry the complete override dict**, every constant and every swept parameter.
> `run.py:assert_uniform_overrides()` refuses to submit anything else, and
> `tests/experiments/test_paramspace_design.py` pins it — including two tests that check the refusal
> actually fires.

## Cost

Measured at **~23.5 runs/s on 10 workers** over a 1200-run trial, which projected to roughly 2.5 hours
for the full 204,800 runs. `run.py` checkpoints per configuration and resumes, so it can be interrupted.

Measure it yourself before committing the machine:

```bash
python3 experiments/20260811_paramspace/run.py --arms 20 --workers 10
```

## Reproducing

```bash
python3 -m pip install -r requirements.txt

python3 experiments/20260811_paramspace/design.py        # design.json, deterministic from its seed
python3 experiments/20260811_paramspace/dump_config.py   # config-used.json: the commit + all settings

python3 experiments/20260811_paramspace/run.py --workers 10    # the sweep. Hours. Resumable.

python3 experiments/20260811_paramspace/analyse.py       # arms.csv, summary.json
python3 experiments/20260811_paramspace/cluster.py       # clusters.csv, cluster-summary.json
python3 experiments/20260811_paramspace/figures.py       # figures/*.png
python3 experiments/20260811_paramspace/report.py        # report.md, .html, .pdf
```

Every script takes `--arms N` or `--in-dir` / `--out-dir` so the whole chain can be exercised on a small
slice without touching the real results:

```bash
python3 experiments/20260811_paramspace/run.py     --arms 60 --runs 20 --out /tmp/probe
python3 experiments/20260811_paramspace/analyse.py --arms 60 --runs-dir /tmp/probe --out-dir /tmp/probe
python3 experiments/20260811_paramspace/cluster.py --in-dir /tmp/probe
python3 experiments/20260811_paramspace/figures.py --in-dir /tmp/probe
python3 experiments/20260811_paramspace/report.py  --in-dir /tmp/probe
```

**Set the run length through `BATCH_SIZE` in `design.py`, never through a step count.** The model stops
itself at its own `BATCH_SIZE`, and a loop bound below it scores a truncated run as *won* — see the note
in `sim/cli/main.py`.

## Files

| File | Committed | What it is |
|---|---|---|
| `design.py` | ✅ | the Sobol design. The single definition of what was run |
| `run.py` | ✅ | the sweep, on one process pool. Resumable |
| `dump_config.py` | ✅ | records the commit and every setting as actually applied |
| `analyse.py` | ✅ | per-arm aggregation, intervals, and the validity checks |
| `cluster.py` | ✅ | K-means, difficulty ranking, and the k-NN validation |
| `figures.py` | ✅ | the six report figures, matplotlib |
| `report.py` | ✅ | assembles `report.md` from the JSON, renders HTML, prints the PDF |
| `report.md` | ✅ | **the write-up.** Every number in it is read from the JSON, none typed by hand |
| `paramspace-report.pdf` | ✅ | the same, printed |
| `design.json` | — | rebuildable from `design.py` and its seed |
| `runs/` | — | raw per-run JSON and `results.csv`; gitignored, ~200 MB |
| `arms.csv`, `summary.json` | — | `analyse.py` output; gitignored |
| `clusters.csv`, `cluster-summary.json` | — | `cluster.py` output; gitignored |
| `config-used.json`, `figures/` | — | gitignored |

`.gitignore` excludes `experiments/**/*.json` and `experiments/**/*.csv`, which is why the reproduce
commands above are literal: they are the only record of how the artefacts were made.

## What this will not tell you

- **Anything about UAVs.** This is the baseline the adaptation experiments are measured *against*.
- **How `BATCH_SIZE` moves the surface.** Held at 100. It is the strongest difficulty dial there is,
  which is exactly why sweeping it alongside the others would have swamped them.
- **How grid size moves it.** Held at 100 × 100.
- **Anything about a wind that changes mid-run.** `WIND_VARIABILITY` is `None` throughout.
