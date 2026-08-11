# Wind against the no-UAV baseline — 10 August 2026

> **The wind model changed on 11 August 2026, after this experiment was run.** `FIXED_WIND`, `FIRST_DIR`,
> `SECOND_DIR` and `FIRST_DIR_PROB` no longer exist: `WIND_DIRECTION` is now a list of the 8 compass
> points drawn from uniformly, held for `WIND_VARIABILITY` steps at a time, and the diagonals are
> directions in their own right rather than two cardinals mixed per cell. See the Wind section of
> `README.md`.
>
> The numbers below are still a correct account of the simulator as it was at the commit named next, and
> the `cardinal` arms carry over unchanged — cardinal spread is bit-for-bit what it was, which is the
> property the change was made to preserve. **`run.sh` and `dump_config.py` will not run as written**:
> they pass settings that have been deleted. The `diagonal` and `steadiness` sweeps measure a mechanism
> that no longer exists at all, and re-running them would need re-designing rather than re-writing. Left
> as they are, deliberately, because they are the record of what was actually run.

What the wind does to the loss rate on a 100x100 map, measured against
[`experiments/20260810_baseline/`](../20260810_baseline/README.md), which lost the home base in all 5 000
of its runs with no wind and no UAVs.

**Result: wind is not a difficulty dial over most of its range. From `MU` = 0 to `MU` = 0.75 the loss rate
is indistinguishable from the no-wind baseline in all four cardinal directions — 99.5% or above against
the baseline's 100.0%. Above 0.85 it collapses, and how far it collapses depends more on which way the
wind blows than on how hard.**

Run at commit **`d08da5f851ec87026d7d973b159e29d34de88689`** ("Create simulation baseline without any UAVs
on 100x100 grid"). That commit added only the baseline write-up — no simulator code changed between it and
the baseline's own commit `34276b2`, so the two experiments measure the same simulator.

`wind-report.pdf` is the full write-up. `wind-report.html` is its source; regenerate the PDF with:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
    --no-pdf-header-footer --print-to-pdf=wind-report.pdf wind-report.html
```

## What was measured

Every arm holds the baseline's twelve settings fixed and changes nothing but the wind, so the baseline is
the arm this whole surface is read against.

| Setting | Baseline | Here |
|---|---|---|
| `ACTIVATE_WIND` | False | **True** |
| `FIXED_WIND` | — | True (cardinal) / False (diagonal) |
| `WIND_DIRECTION` | — | north, south, east, west |
| `FIRST_DIR`, `SECOND_DIR` | — | the four perpendicular pairs, `FIRST_DIR_PROB` = 0.5 |
| `MU` | — | 0, 0.25, 0.5, 0.75, 0.85, 0.9, 0.95, 0.975, 0.99, 1.0 |
| everything else | | unchanged from the baseline |

`WIDTH`/`HEIGHT` 100, `BATCH_SIZE` 100, `NUM_AGENTS` 0, `BHP` 4, `FIRE_START_POSITION` random,
`FIRE_START_STEP` 0, `BURNING_RATE` 1, `FIRE_SPREAD_SPEED` 1, `DENSITY_PROB` 1.0, `ACTIVATE_SMOKE` False,
`ACTIVATE_FIREFIGHTING` True. `config-used.json` records all 90 settings as applied, with the commit.

1 000 runs per arm, seeds 3 000 000 – 3 000 999, disjoint from every other experiment in the repository.
The `MU` levels are deliberately uneven — four below 0.85 to establish that the flat region is flat, six
above it where the response actually moves.

## Comparison with the baseline

| | n | lost | loss rate | 95% Wilson |
|---|---|---|---|---|
| **no-UAV baseline, no wind** | 5 000 | 5 000 | **100.00%** | 99.92 – 100.00 |
| wind on, `MU` = 0 (all four directions) | 1 000 | 1 000 | **100.00%** | 99.62 – 100.00 |
| wind on, `MU` = 0.75, worst direction | 1 000 | 995 | 99.50% | 98.83 – 99.79 |
| wind on, `MU` = 0.9, south | 1 000 | 970 | 97.00% | 95.75 – 97.89 |
| wind on, `MU` = 0.9, north | 1 000 | 646 | 64.60% | 61.59 – 67.50 |
| wind on, `MU` = 1.0, north | 1 000 | 3 | 0.30% | 0.10 – 0.88 |

The two experiments **cannot be paired** — the baseline drew its fires from seeds 1 000 000 upwards and
this one from 3 000 000, deliberately, because reusing a seed block across experiments is not pairing, it
is fitting every measurement ever taken to one set of fires. The comparison is therefore between
independent samples, and the honest internal comparator is the `MU` = 0 arms: the same code with the wind
switched on and turned all the way down, on this experiment's own fires. Those lost 1 000 of 1 000,
reproducing the baseline on a seed block it never touched.

Ten of the forty cardinal arms have intervals containing the baseline's 100.0% outright: every direction
at `MU` ≤ 0.25, and three of four at `MU` = 0.5.

## Results

### The four cardinal directions

Loss rate, 1 000 runs per cell, 95% Wilson interval beneath.

| MU | north | south | east | west |
|---|---|---|---|---|
| 0 | 100.0 <br><sub>99.6–100</sub> | 100.0 <br><sub>99.6–100</sub> | 100.0 <br><sub>99.6–100</sub> | 100.0 <br><sub>99.6–100</sub> |
| 0.25 | 100.0 <br><sub>99.6–100</sub> | 100.0 <br><sub>99.6–100</sub> | 100.0 <br><sub>99.6–100</sub> | 100.0 <br><sub>99.6–100</sub> |
| 0.5 | 99.9 <br><sub>99.4–100</sub> | 100.0 <br><sub>99.6–100</sub> | 100.0 <br><sub>99.6–100</sub> | 99.8 <br><sub>99.3–99.9</sub> |
| 0.75 | 99.6 <br><sub>99.0–99.8</sub> | 99.9 <br><sub>99.4–100</sub> | 99.9 <br><sub>99.4–100</sub> | 99.5 <br><sub>98.8–99.8</sub> |
| 0.85 | 95.2 <br><sub>93.7–96.4</sub> | 99.4 <br><sub>98.7–99.7</sub> | 95.9 <br><sub>94.5–97.0</sub> | 99.0 <br><sub>98.2–99.5</sub> |
| **0.9** | **64.6** <br><sub>61.6–67.5</sub> | **97.0** <br><sub>95.8–97.9</sub> | **65.5** <br><sub>62.5–68.4</sub> | **97.6** <br><sub>96.5–98.4</sub> |
| 0.95 | 10.6 <br><sub>8.8–12.7</sub> | 53.7 <br><sub>50.6–56.8</sub> | 12.6 <br><sub>10.7–14.8</sub> | 50.8 <br><sub>47.7–53.9</sub> |
| 0.975 | 2.8 <br><sub>1.9–4.0</sub> | 29.2 <br><sub>26.5–32.1</sub> | 3.3 <br><sub>2.4–4.6</sub> | 26.4 <br><sub>23.8–29.2</sub> |
| 0.99 | 1.1 <br><sub>0.6–2.0</sub> | 13.6 <br><sub>11.6–15.9</sub> | 1.2 <br><sub>0.7–2.1</sub> | 14.1 <br><sub>12.1–16.4</sub> |
| 1.0 | 0.3 <br><sub>0.1–0.9</sub> | 1.0 <br><sub>0.5–1.8</sub> | 0.4 <br><sub>0.2–1.0</sub> | 1.6 <br><sub>1.0–2.6</sub> |

Three regions, and only the third is the one anybody would predict:

- **Below `MU` = 0.75 the wind does not exist**, as far as the base is concerned. All sixteen arms lost
  ≥ 99.5%. By 0.75 the wind has already thrown away three quarters of every off-axis spread weight and
  raised the front speed from 1.44 to 2.74 cells per update — it has transformed the fire — and the loss
  rate has not moved.
- **Between 0.85 and 0.99 the direction decides everything.** At `MU` = 0.9, south and west lose 97% while
  north and east lose 65%. A factor of five, from nothing but which way the air moves.
- **At `MU` = 1 everything collapses together**, to between 0.3% and 1.6%.

### Why direction matters: the map, not the wind

The base sits at (25, 25) on a 100x100 grid — a quarter of the way in, not in the middle. A wind driving
fire towards decreasing coordinates has **73 rows of grid upwind of the base** to draw ignitions from; one
driving the other way has **25**. South and west are the long-approach directions, north and east the
short ones, and that 73:25 ratio is the whole of the effect. **It would vanish on a map with a centred
base**, which is worth knowing before this result is carried anywhere else.

### The four diagonals

A diagonal wind is not a direction in this model. It is a *mixture*: each cell/neighbour pair blows
`FIRST_DIR` with probability `FIRST_DIR_PROB` and `SECOND_DIR` otherwise, and 0.5 is the even split that
puts the resultant on the diagonal.

| MU | north+east | north+west | south+east | south+west |
|---|---|---|---|---|
| 0 | 100.0 | 100.0 | 100.0 | 100.0 |
| 0.25 | 100.0 | 100.0 | 100.0 | 100.0 |
| 0.5 | 99.9 | 100.0 | 100.0 | 100.0 |
| 0.75 | 99.4 | 99.7 | 99.6 | — |
| 0.85 | 95.9 | 99.2 | 99.5 | — |
| 0.9 | 75.8 | 97.1 | 96.0 | — |
| 0.95 | 23.5 | 55.6 | 59.1 | — |
| 0.975 | 8.7 | 28.3 | 31.9 | — |
| 0.99 | 7.2 | 21.9 | 24.3 | — |
| **1.0** | **6.8** <br><sub>5.4–8.5</sub> | **18.5** <br><sub>16.2–21.0</sub> | **20.3** <br><sub>17.9–22.9</sub> | — |

**A diagonal wind is far less protective than a cardinal one.** At full strength a cardinal wind leaves a
loss rate of 0.3–1.6%; a diagonal one leaves 6.8–20.3%, up to twenty times higher. The reason is that
"diagonal" here means an alternating mixture, so even at `MU` = 1 the fire can still step two ways and
stays two-dimensional, where a cardinal wind at `MU` = 1 collapses it to a line one cell wide.

The `south+west` column is missing above 0.5: the sweep was interrupted before those arms ran, and its
`MU` = 0.75 arm was discarded because 256 of its 1 000 runs were killed mid-flight (see *What was not run*).

### What the wind does to the fire, as opposed to the base

Mean cells burned per run, south wind:

| MU | 0 | 0.25 | 0.5 | 0.75 | 0.85 | 0.9 | 0.95 | 0.975 | 0.99 | 1.0 |
|---|---|---|---|---|---|---|---|---|---|---|
| cells burned | 5 895 | 5 683 | 5 365 | 4 727 | 4 111 | 3 560 | 1 944 | 1 057 | 520 | 37 |
| loss rate | 100.0 | 100.0 | 100.0 | 99.9 | 99.4 | 97.0 | 53.7 | 29.2 | 13.6 | 1.0 |

Between `MU` = 0 and 0.75 the wind removes a fifth of the burned area and changes the loss rate by one
tenth of one point. The knob is connected; it is just not connected to the outcome. (Runs that are lost
stop early, so this figure mixes fire extent with run duration — the comparison is fair across the top
half of the table, where median step of loss moves only from 28 to 30, and progressively less so below it.)

## Mechanism

Two facts from the code account for everything above.

**1. The wind makes the fire faster and thinner at once.** It does not add a term to the spread weight; it
moves weight between directions. Every off-axis weight is multiplied by exactly (1 − `MU`), reaching zero
only at `MU` = 1. Meanwhile the three on-axis weights are pushed to certainty, taking the downwind front
from 1.44 to a guaranteed 3.00 cells per update:

| MU | 0 | 0.25 | 0.5 | 0.75 | 0.85 | 0.9 | 0.95 | 0.975 | 0.99 | 1.0 |
|---|---|---|---|---|---|---|---|---|---|---|
| downwind d=1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| downwind d=3 | 0.111 | 0.333 | 0.556 | 0.778 | 0.867 | 0.911 | 0.956 | 0.978 | 0.991 | 1.000 |
| crosswind d=1 | 1.000 | 0.750 | 0.500 | 0.250 | 0.150 | 0.100 | 0.050 | 0.025 | 0.010 | 0.000 |
| front speed | 1.44 | 1.96 | 2.39 | 2.74 | 2.85 | 2.90 | 2.95 | 2.98 | 2.99 | 3.00 |

**2. The fire is a wave, and the base is destroyed by dwell.** A burning cell burns for *one* fire update
and goes out, so the fire is a wave a few cells deep travelling across the grid, not a growing region of
flame. The base is not destroyed by fire reaching it: it takes one point of damage per step on which any
of its four cells is alight, and is lost at `BHP` = 4 of them.

So what kills the base is **dwell** — how many consecutive steps the wave stands on the footprint. A wide
slow fire dwells; a narrow fast one crosses in two or three steps and is gone. Wind does not keep the fire
away from the base. It makes the fire arrive sooner, cross faster, and leave. **The base survives because
it was singed rather than besieged.**

## Validity

Four checks, all passing. A flat surface is exactly what a wind setting that silently failed to apply
would also produce, so the checks matter more here than in the baseline.

| Check | Result |
|---|---|
| **Pairing.** The ignition cell is drawn at `model.py:88`, before the wind is built at `model.py:109`, so a seed must name the same fire in every arm. | 1 000 seeds, one ignition cell each, across all 80 arms |
| **`MU` = 0 is directionless.** Zero strength leaves every kernel weight untouched, so the four directions must agree *run for run*, not merely in rate. | 4 arms identical run for run; 100.00% over 4 000 runs |
| **The `MU` = 1 geometry.** At full strength the fire is a line, so it is lost if and only if the ignition lies on the two-cell strip through the base and upwind of it — a prediction about *which runs*. | 32 predicted, 32 actual, **0 mismatches** in all four directions |
| **Baseline replication.** `MU` = 0 on a disjoint seed block must reproduce the no-wind baseline. | 1 000 / 1 000 lost, against the baseline's 5 000 / 5 000 |

The line-fire rule is stated for ignitions further than three cells from the base. Inside that, the wave's
first leap clears the two-deep footprint in a single step and scores 2–3 damage against the 4 required;
three such runs occurred and one was lost. That boundary case is *why* the dwell mechanism above is the
right reading, so it is reported rather than smoothed over.

## What was not run

The sweep was stopped part way. Three further sweeps were designed and are still in `run.sh`, and none of
them has data:

- **`runlength`** — `BATCH_SIZE` ∈ {50, 100, 200, 400} × `MU`. This is the one worth running next. The
  finding that wind does nothing below 0.85 is a claim about a 100-step budget, and the run length is
  where it would break.
- **`steadiness`** — `FIRST_DIR_PROB` ∈ {0.5 … 1.0}, how steady a composed wind is. At 1.0 it collapses to
  a fixed wind, which would check the two wind code paths against each other.
- **`extent`** — `MU` with the base switched off, so every run lasts the full 100 steps and burned area is
  not confounded with run duration. The burned-area table above is the confounded version of this.

Also missing: `south+west` at `MU` ≥ 0.75 (4 arms), and the discarded `south+west` `MU` = 0.75 arm.

## Reproducing

```bash
bash experiments/20260810_wind/run.sh            # all five sweeps, hours of wall time
python3 experiments/20260810_wind/analyse.py     # arms.csv, summary.json, the four checks
python3 experiments/20260810_wind/dump_config.py # config-used.json
python3 experiments/20260810_wind/figures.py all # the charts and tables in the report
```

`analyse.py` reads the per-arm JSON rather than the merged `runs.csv`, because `tools/sweep.py` writes the
CSV only when a whole scan finishes and an interrupted scan still leaves good arms on disk. It discards any
arm containing an errored run outright rather than reporting a rate over whichever runs happened to finish.

**Set the run length through `BATCH_SIZE`, never `--steps`** — they are aliases for one setting.
`--policy random` is recorded for completeness only; with `NUM_AGENTS = 0` no policy is ever consulted.

## Files

| Path | Contents |
|---|---|
| `run.sh` | every arm of all five sweeps |
| `analyse.py` | produces `arms.csv` and `summary.json`, and runs the four checks |
| `figures.py` | the SVG charts and HTML tables in the report, generated from `summary.json` |
| `extent.py` | reads the extent sweep, which has no loss rate to summarise (no data yet) |
| `dump_config.py` | produces `config-used.json` |
| `wind-report.html` / `.pdf` | the full write-up |
| `runs/*/` | raw `headless.py` output, one JSON per arm — gitignored |
| `arms.csv`, `summary.json`, `config-used.json` | gitignored; regenerate with the commands above |
