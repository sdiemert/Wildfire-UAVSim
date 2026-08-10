# No-UAV loss rate baseline — 10 August 2026

The no-treatment arm every later policy comparison is measured against: how often the home base is
destroyed on a 100x100 map with nothing flown against the fire.

**Result: the base is destroyed in every one of 5000 independently seeded runs. Loss rate 100.0%,
95% Wilson interval 99.92 – 100.00.**

Run at commit **`34276b2db4bf2eab0d506ba3830bd57af6cc67ca`** ("Fix seeding for parallel processing runs"),
with a clean working tree apart from an untracked `.DS_Store`.

`baseline-report.pdf` is the full write-up — the simulation model, every parameter and why it was fixed
there, the seeding and independence argument, the Wilson calculation worked through, and the results.
`baseline-report.html` is its source; regenerate the PDF with:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
    --no-pdf-header-footer --print-to-pdf=baseline-report.pdf baseline-report.html
```

## Parameters

The twelve settings that were specified, and what they are in `config.py`. The five marked ⚠ depart from
the calibrated defaults at this commit, so the figures in `experiments/20260810/` do **not** transfer.

| Specified | Setting | Value | Default |
|---|---|---|---|
| Grid size 100x100 | `WIDTH`, `HEIGHT` | 100, 100 | same |
| Base enabled | `ACTIVATE_FIREFIGHTING` | True | same |
| Base HP 4 | `BHP` | 4 | same |
| Fire start position random | `FIRE_START_POSITION` | `"random"` | same |
| Fire start step 0, fixed | `FIRE_START_STEP` | 0 | ⚠ (10, 20) |
| Batch size 100 | `BATCH_SIZE` | 100 | same |
| Burning rate 1 | `BURNING_RATE` | 1 | same |
| Fire spread speed 1 | `FIRE_SPREAD_SPEED` | 1 | same |
| Vegetation density 1 | `DENSITY_PROB` | 1.0 | ⚠ 0.9 |
| Wind none | `ACTIVATE_WIND` | False | ⚠ True |
| Smoke none | `ACTIVATE_SMOKE` | False | ⚠ True |
| No UAVs | `NUM_AGENTS` | 0 | ⚠ 4 |

Everything else took its `config.py` default. `config-used.json` records all 90 settings as they were
actually applied, together with the commit, so a later reader can diff rather than assume.

## Results

| Arm | n | lost | loss rate | 95% Wilson |
|---|---|---|---|---|
| **no UAVs, 100 steps** | **5000** | **5000** | **100.00%** | **99.92 – 100.00** |
| control, truncated to 20 steps | 1000 | 331 | 33.10% | 30.25 – 36.08 |

Loss rate by distance from the ignition cell to the base footprint (Chebyshev; the grid's maximum is 73):

| Distance | n | lost | loss rate | 95% Wilson | mean step of loss |
|---|---|---|---|---|---|
| [0, 20) | 811 | 811 | 100.00% | 99.53 – 100.00 | 12.0 |
| [20, 40) | 1442 | 1442 | 100.00% | 99.73 – 100.00 | 20.4 |
| [40, 60) | 1439 | 1439 | 100.00% | 99.73 – 100.00 | 31.1 |
| [60, 73] | 1308 | 1308 | 100.00% | 99.71 – 100.00 | 39.7 |

Step of loss: min 5, median 27, mean 27.2, 95th percentile 44, **max 54** against a 100 step budget.
Regressing the step of loss on ignition distance gives `5.34 + 0.5161 · distance` with Pearson r = 0.964,
so the front advances at **1.94 cells per step** and the fixed cost at the base is ~5 steps (`BHP` = 4
plus arrival).

### Things worth knowing before using this baseline

- **The 100 step budget is not what decides it.** The slowest run of 5000 was lost at step 54, and the
  ignition distances sampled reach the grid maximum. The loss rate stays 100% on these seeds at any
  `BATCH_SIZE` from 54 up — unusual for this simulator, where run length is normally the strongest
  difficulty dial there is.
- **Distance to the fire does not matter, only timing.** Ignitions in the far corners still destroy the
  base in every run, 46 steps inside the budget.
- **The baseline has no headroom below.** At exactly 100% every subsequent win is attributable to the
  UAVs — a policy's win rate *is* its effect size — but this configuration cannot separate a policy that
  saves 0 runs in 1000 from one that saves 1. If a later experiment needs discrimination at the weak end,
  the lever is the difficulty (density, ignition step, wind), not the baseline, and this baseline has to
  be re-measured after any such change.
- **Wind off is a hardening, not a softening.** The calibration experiment found stronger wind made the
  scenario *easier*, because it concentrates the fire into a ray that misses a 2x2 base. Isotropic spread
  reaches the base from anywhere.

### Why there is a control arm

A rate of exactly 100% with zero variance is the same reading a broken outcome field would give. The
control arm re-runs the identical configuration truncated to `BATCH_SIZE=20` — inside the body of the
step-of-loss distribution — on a seed block the main arm never touched. It lost 33.10% of runs against
**31.34% predicted** from the main arm's step-of-loss distribution, and the prediction falls inside the
observed interval. So the outcome field does record WON when a run is won, the two seed blocks agree, and
the step-of-loss distribution predicts an independent experiment.

## Method

Runs are independent by construction: run *i* is seeded `base_seed + i`, and `seed_simulation()` replaces
`config.SYSTEM_RANDOM` — the only generator the simulation draws from — with a fresh `random.Random(seed)`
before each model is built. No state crosses between runs. `analyse.py` refuses the batch if any run
errored, if any outcome is neither WON nor LOST, or if two runs share a seed.

Seed blocks are disjoint from every other experiment in this repository (20260810 used 1000 for fitting
and 500000 for validation):

| Arm | n | seeds |
|---|---|---|
| main | 5000 | 1000000 – 1004999 |
| control | 1000 | 2000000 – 2000999 |

n = 5000 was fixed before the batch ran. Near p = 1 the informative quantity is the Wilson lower bound,
which for a unanimous sample is n / (n + z²) and depends on nothing but n: 96.3% at n = 100, 99.62% at
1000, 99.92% at 5000, 99.98% at 20000. 5000 also keeps the interval useful in the case that did not
happen — at a true rate near 97% it would have given about ±0.5 points. The batch cost 897 s of CPU across
8 workers, about two and a half minutes of wall time.

The interval is Wilson rather than Wald because Wald collapses to the degenerate point [100%, 100%] at
p̂ = 1: its standard error is exactly zero. The whole width of the Wilson interval here comes from its
z²/4n² term. `wilson()` is imported from `tools/sweep.py` rather than reimplemented, so this experiment
and the repository's sweep tool cannot disagree about what a 95% interval is.

## Reproducing

From the repository root, at the commit above:

```bash
# main arm -- 5000 runs, no UAVs, ~2.5 minutes of wall time on 8 workers
python3 headless.py \
    --runs 5000 --workers 8 --seed 1000000 --policy random --managing none \
    --log-every 0 --log-level ERROR \
    --set WIDTH=100 --set HEIGHT=100 --set BATCH_SIZE=100 --set NUM_AGENTS=0 \
    --set ACTIVATE_FIREFIGHTING=True --set BHP=4 \
    --set 'FIRE_START_POSITION=random' --set FIRE_START_STEP=0 \
    --set BURNING_RATE=1 --set FIRE_SPREAD_SPEED=1 --set DENSITY_PROB=1.0 \
    --set ACTIVATE_WIND=False --set ACTIVATE_SMOKE=False \
    --output experiments/20260810_baseline/runs/no-uav.json

# control arm -- the same, truncated to 20 steps, on a disjoint seed block
python3 headless.py \
    --runs 1000 --workers 8 --seed 2000000 --policy random --managing none \
    --log-every 0 --log-level ERROR \
    --set WIDTH=100 --set HEIGHT=100 --set BATCH_SIZE=20 --set NUM_AGENTS=0 \
    --set ACTIVATE_FIREFIGHTING=True --set BHP=4 \
    --set 'FIRE_START_POSITION=random' --set FIRE_START_STEP=0 \
    --set BURNING_RATE=1 --set FIRE_SPREAD_SPEED=1 --set DENSITY_PROB=1.0 \
    --set ACTIVATE_WIND=False --set ACTIVATE_SMOKE=False \
    --output experiments/20260810_baseline/runs/control-20-steps.json

python3 experiments/20260810_baseline/analyse.py       # results.csv, summary.json
python3 experiments/20260810_baseline/dump_config.py   # config-used.json
```

`--policy random` is recorded for completeness only; with `NUM_AGENTS = 0` no policy is ever consulted.
**Set the run length through `BATCH_SIZE`, never `--steps`** — `--steps` is an alias for the same setting,
and the two disagreeing is an error, but `BATCH_SIZE` is the one the model actually stops itself on.

## Files

| Path | Contents |
|---|---|
| `runs/no-uav.json` | raw `headless.py` output, 5000 records |
| `runs/control-20-steps.json` | raw `headless.py` output, 1000 records |
| `results.csv` | long format, one row per main-arm run, ignition distance joined on |
| `summary.json` | every number quoted above |
| `config-used.json` | all 90 settings as applied, plus the commit |
| `analyse.py` | produces `results.csv` and `summary.json` |
| `dump_config.py` | produces `config-used.json` |
| `baseline-report.html` / `.pdf` | the full write-up |
