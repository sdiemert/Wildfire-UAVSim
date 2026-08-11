#!/bin/bash
# Runs every arm of the wind experiment. From the repository root:  bash experiments/20260810_wind/run.sh
#
# Five scans, on four disjoint seed blocks. Every arm holds the twelve settings of
# experiments/20260810_baseline/ fixed except the wind, so the no-wind baseline (100% loss over 5000 runs)
# is the arm this whole surface is read against.
#
# The MU levels are not evenly spaced. A pilot found the loss rate pinned at 100% from MU = 0 to MU = 0.75
# and 1% at MU = 1.0, so an even grid would have spent nine tenths of its arms measuring the same flat
# 100% twice over. The levels below put four points below the cliff to establish that it is flat, and six
# between 0.85 and 1.0 to resolve the edge.

set -euo pipefail

cd "$(dirname "$0")/../.."

COMMON=(--policy random --managing none --workers 8 --log-level ERROR
        --base WIDTH=100 --base HEIGHT=100 --base BATCH_SIZE=100 --base NUM_AGENTS=0
        --base ACTIVATE_FIREFIGHTING=True --base BHP=4
        --base FIRE_START_POSITION=random --base FIRE_START_STEP=0
        --base BURNING_RATE=1 --base FIRE_SPREAD_SPEED=1 --base DENSITY_PROB=1.0
        --base ACTIVATE_SMOKE=False)

MU=MU=0.0,0.25,0.5,0.75,0.85,0.9,0.95,0.975,0.99,1.0


# --- the four cardinal directions -------------------------------------------
#
# FIXED_WIND draws nothing from SYSTEM_RANDOM (see the note in sim/fire_spread.py), so within this scan a
# run index means the same ignition cell in all forty arms and the comparison between directions is paired
# on the fire. analyse.py checks that rather than trusting it.

python3 tools/sweep.py scan "${COMMON[@]}" \
    --runs 1000 --seed 3000000 \
    --base ACTIVATE_WIND=True --base FIXED_WIND=True \
    --axis WIND_DIRECTION=north,south,east,west \
    --axis "$MU" \
    --out experiments/20260810_wind/runs/cardinal

# --- the four diagonals ------------------------------------------------------
#
# There is no diagonal wind direction. Composing two perpendicular ones is how config.py says to ask for
# one: each cell/neighbour pair blows FIRST_DIR with probability FIRST_DIR_PROB and SECOND_DIR otherwise,
# and 0.5 is the even split that puts the resultant on the diagonal. Unlike a fixed wind this draws from
# SYSTEM_RANDOM, but it draws only after the ignition cell has been chosen (model.py:88 against :109), so
# these arms still see the same fires as the cardinal ones. analyse.py checks that rather than assuming it.

python3 tools/sweep.py scan "${COMMON[@]}" \
    --runs 1000 --seed 3000000 \
    --base ACTIVATE_WIND=True --base FIXED_WIND=False --base FIRST_DIR_PROB=0.5 \
    --axis FIRST_DIR=north,south \
    --axis SECOND_DIR=east,west \
    --axis "$MU" \
    --out experiments/20260810_wind/runs/diagonal

# --- the cliff against run length --------------------------------------------
#
# The wind narrows the fire long before it saves the base: at MU = 0.75 the off axis weights are already
# down to a quarter, and the loss rate has not moved. The reason is that a narrower fire is also a faster
# one along its axis, and 100 steps is more time than either version of the fire needs. Whether that stays
# true is a question about the run length rather than about the wind, so it is measured rather than
# asserted: the same south wind against a batch of 50, 100, 200 and 400 steps.

python3 tools/sweep.py scan "${COMMON[@]}" \
    --runs 500 --seed 4000000 \
    --base ACTIVATE_WIND=True --base FIXED_WIND=True --base WIND_DIRECTION=south \
    --axis BATCH_SIZE=50,100,200,400 \
    --axis MU=0.5,0.75,0.85,0.9,0.95,0.975,0.99,1.0 \
    --out experiments/20260810_wind/runs/runlength

# --- how steady the wind is --------------------------------------------------
#
# A composed wind is not only a direction, it is a mixture: FIRST_DIR_PROB says how often each cell blows
# the predominant way rather than the other. That is a spread parameter in its own right -- it sets how
# wide the cone is -- and it is the one setting of the three that has no cardinal equivalent. Swept at the
# two strengths where anything is happening at all, since below MU = 0.9 nothing is.
#
# The 1.0 end is a check rather than a measurement: a composed wind that blows FIRST_DIR every time is a
# fixed wind, and has to reproduce the matching arm of the cardinal sweep.

python3 tools/sweep.py scan "${COMMON[@]}" \
    --runs 500 --seed 5000000 \
    --base ACTIVATE_WIND=True --base FIXED_WIND=False \
    --base FIRST_DIR=south --base SECOND_DIR=east \
    --axis FIRST_DIR_PROB=0.5,0.6,0.7,0.8,0.9,1.0 \
    --axis MU=0.95,1.0 \
    --out experiments/20260810_wind/runs/steadiness

# --- what the wind does to the fire itself -----------------------------------
#
# The loss rate is flat below MU = 0.9, which invites the reading that the wind is doing nothing there. It
# is doing a great deal; it is just not doing anything the base notices. Measuring that needs runs that do
# not stop early, so this arm switches the home base off entirely (ACTIVATE_FIREFIGHTING=False, outcome
# N/A) and every run goes the full hundred steps. What is read off it is the burned area, which is a clean
# measure of how far the fire got with nothing to interrupt it.
#
# analyse.py refuses an N/A outcome, correctly -- it is summarising loss rates. This sweep is read by
# extent.py instead.

python3 tools/sweep.py scan "${COMMON[@]}" \
    --runs 200 --seed 6000000 \
    --base ACTIVATE_FIREFIGHTING=False \
    --base ACTIVATE_WIND=True --base FIXED_WIND=True --base WIND_DIRECTION=south \
    --axis MU=0.0,0.25,0.5,0.75,0.85,0.9,0.95,0.975,0.99,1.0 \
    --out experiments/20260810_wind/runs/extent
