# Difficulty calibration — 10 August 2026

Re-choosing six `config.py` defaults so that an unmanaged `firefighter` team wins about one run in ten.
**Result: 10.9% (95% Wilson 9.1 – 13.0)** over 1000 seeds that took no part in the fitting.

`calibration-report.pdf` is the full write-up — objective, the simulation model, the sweep methodology,
all results, and the complete configuration. `calibration-report.html` is its source; regenerate the PDF
with:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
    --no-pdf-header-footer --print-to-pdf=calibration-report.pdf calibration-report.html
```

## What changed in config.py

| Setting | was | now |
|---|---|---|
| `WIDTH`, `HEIGHT` | 50, 50 | 100, 100 |
| `BATCH_SIZE` | 100 | 100 — unchanged, but now a calibrated value |
| `FIRE_SPREAD_SPEED` | 2 | 1 |
| `BHP` | 5 | 4 |
| `WATER_EXTINGUISH_PROB_CENTRE` | 0.95 | 0.76 |
| `WATER_EXTINGUISH_PROB_EDGE` | 0.60 | 0.48 |

## The data

21 800 runs in 81 arm files. Every `runs.csv` is long format — one row per run, with the swept parameters
joined on, which is the thing `headless.py` JSON alone cannot tell you.

| Directory | Contents | Runs | Report |
|---|---|---|---|
| `coarse/` | 32-arm surface: spread × BHP × water strength | 3 200 | §4.3 |
| `calibrate/` | bisection probes on the water scale | 1 200 | §4.4 |
| `fine/` | refinement either side of the crossing | 1 600 | §4.4 |
| `batch-size/` | win rate against the step budget | 2 400 | §4.2 |
| `validate/` | held-out seeds, four policies, managed and unmanaged | 7 000 | §1.3 |
| `char-fuel/` | `UAV_FUEL` | 1 000 | §4.5 |
| `char-penalty/` | `UAV_FUEL_WATER_PENALTY` | 800 | §4.5 |
| `char-wind/` | `MU` | 800 | §4.5 |
| `char-grid/` | `GRID` (width and height together) | 800 | §4.5 |
| `char-water/` | `UAV_WATER_CAPACITY` × `BASE_CAPACITY` | 1 200 | §4.5 |
| `char-position/` | `UAV_POSITION_NOISE_MAX` × `_BIAS_MAX` | 800 | §4.5 |

`validate/` holds raw `headless.py` output rather than a sweep, so it has no `runs.csv`; each file is one
policy/managing arm at n = 1000 (n = 500 for `follow-fire` and `random`).

The §4.1 baseline scan was run interactively and its raw output was not retained. Every other figure in
the report is recoverable from the files here.

## Reproducing

Seed block **1000** was used for all searching, seed block **500000** for validation only — nothing was
fitted on it. Arms within a sweep share the block, so comparisons between them are paired.

```bash
python3 tools/sweep.py scan --policy firefighter --managing none --runs 100 --seed 1000 \
    --base WIDTH=100 --base HEIGHT=100 --base BATCH_SIZE=100 \
    --axis FIRE_SPREAD_SPEED=1,2 --axis BHP=2,3,4,5 \
    --axis EXTINGUISH_SCALE=1.0,0.85,0.75,0.65 --out experiments/20260810/coarse

python3 tools/sweep.py calibrate --policy firefighter --managing none --knob EXTINGUISH_SCALE \
    --low 0.65 --high 1.0 --target 0.10 --runs 400 --seed 1000 \
    --base WIDTH=100 --base HEIGHT=100 --base FIRE_SPREAD_SPEED=1 --base BHP=4 \
    --out experiments/20260810/calibrate

python3 headless.py --runs 1000 --workers 8 --seed 500000 \
    --policy firefighter --managing none --log-every 0 \
    --output experiments/20260810/validate/firefighter__none.json
```

**Set the run length with `--set BATCH_SIZE=N`, never `--steps`.** The model stops itself at its own
`BATCH_SIZE`, so a `--steps` above it is inert — this produced a wrong conclusion during the experiment
and is written up in §3.7 of the report.

*Since fixed:* `headless.py --steps N` is now an alias for `--set BATCH_SIZE=N`, and the two disagreeing
is an error rather than a silent winner (`tests/cli/test_run_length.py`). The commands on this page all
set the run length through `BATCH_SIZE`, so the numbers here stand; anything measured with `--steps`
before the fix does not, having run for `min(--steps, BATCH_SIZE)` and scored a shortfall as a win.

## Findings that run against the assumption

- A **bigger grid makes the scenario easier** — random ignition lands further from the base. Raising the
  spread speed decoupled the two; grid size is now close to a free choice.
- **Stronger wind makes it easier**, non-monotonically: it concentrates the fire into a ray that misses a
  small base.
- **The fuel extension has no effect on outcomes at all.** A firefighter refuels for free while collecting
  water; `UAV_FUEL` from 40 to 250 and `UAV_FUEL_WATER_PENALTY` from 0.0 to 1.0 move the win rate by
  nothing.
- **Smoke is not a simulation feature** — `sim/gui/portrayal.py` reads it and nothing else does.
- **Positioning error is about half the difficulty**: 21% with it off against 10.9% with it on.
- The heuristic managing system is worth **+6.6 points to firefighter and nothing to defend-base**. An
  observation about the managing system, not the configuration; investigating it is separate work.
