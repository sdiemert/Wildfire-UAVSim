#!/usr/bin/env python3
"""The parameter space design: which 2048 configurations the sweep runs.

This is the one place that decides what was run. run.py executes the arms it produces, analyse.py joins
its results back onto them and cluster.py reads the parameter values out of it, so a design that lived in
three places -- or worse, in a shell script and a comment -- is how the arms and the analysis come to
disagree about what a row means.

The design is a *scrambled Sobol sequence*, not a grid. A coarse full factorial over these eight
parameters at three levels each is ~2400 arms and covers the space with a lattice; a distance based
clustering run over a lattice mostly recovers the lattice. Sobol fills the same budget with points that
are spread evenly at every scale, so the clusters that come out are features of the difficulty surface
rather than of the sampling. 2048 is a power of two because that is the point count at which Sobol's
balance properties actually hold -- scipy warns otherwise.

Seven continuous dimensions are drawn from the sequence. Wind direction is the eighth parameter and is
categorical, so it is *stratified* instead: arm j takes COMPASS[j % 8], which gives exactly 256 arms per
direction. Sobol points arrive in scrambled order, so this is a balanced assignment rather than a
correlated one.

Two mappings are worth reading before changing them:

  * fuel. config.validate() requires 1 <= FUEL_BOTTOM_LIMIT <= FUEL_UPPER_LIMIT. Rather than sample a
    square and throw away the invalid half -- which would both waste budget and bias the retained points
    -- the upper limit is drawn from the interval that starts at the bottom limit. The constraint then
    holds by construction and the valid triangle is covered uniformly.

  * wind. Every arm runs with ACTIVATE_WIND on, and MU = 0 is the no wind end of the range rather than a
    separate flag. MU is the contrast between downwind and elsewhere, so MU = 0 leaves the spread
    probability untouched everywhere and *is* a still day. Keeping the flag on means the feature space
    the clustering runs over is continuous, instead of having a discrete hole in it where the wind
    arms stop and the windless ones start.

Writes design.json. Run from the repository root:  python3 experiments/20260811_paramspace/design.py
"""

from __future__ import annotations

# python libraries

import json
import pathlib
import sys

import numpy as np
from scipy.stats import qmc

# own python modules

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

HERE = pathlib.Path(__file__).resolve().parent

# --- the design -------------------------------------------------------------

# Fixed, so that design.json can be regenerated identically from the seed alone rather than having to be
# preserved as an artefact. Changing it changes which configurations were measured.
DESIGN_SEED = 20260811

# a power of two: scipy's Sobol engine only guarantees its balance properties at these sizes
N_ARMS = 2048

RUNS_PER_ARM = 100

# The seed block this experiment draws its fires from. 1000 and 500000 went to the calibration,
# 1000000 and 2000000 to the baseline, 3000000-6000000 to the wind sweeps. Blocks are never reused
# across experiments: two experiments sharing fires are not the independent measurements they look like.
SEED_BASE = 7_000_000

# the 8 point compass, in the order config.WIND_HEADINGS declares it
COMPASS = ("NORTH", "NORTH_EAST", "EAST", "SOUTH_EAST",
           "SOUTH", "SOUTH_WEST", "WEST", "NORTH_WEST")

# Every arm holds these. They are what makes the measurement "how hard is this wildfire on its own":
# no UAVs, no managing system, and a home base for the fire to destroy, since it is the base that is lost
# and without ACTIVATE_FIREFIGHTING every run scores N/A instead of WON or LOST.
CONSTANTS = {
    "WIDTH": 100,
    "HEIGHT": 100,
    "BATCH_SIZE": 100,
    "NUM_AGENTS": 0,
    "MANAGING_SYSTEM": "none",
    "ACTIVATE_FIREFIGHTING": True,
    "BASE_POSITION": None,
    "BASE_SIZE": (2, 2),
    "NUM_OUT_BUILDINGS": 0,
    "FIRE_START_POSITION": "random",
    "FIRE_START_STEP": 0,
    "ACTIVATE_SMOKE": False,
    "ACTIVATE_WIND": True,
    # one direction for the whole run, so the arm's wind is the direction it was assigned rather than a
    # sample from it. WIND_DIRECTION is a list drawn from every WIND_VARIABILITY steps otherwise.
    "WIND_VARIABILITY": None,
    # the UAV extensions. Irrelevant with no UAVs, switched off so they cannot contribute anything.
    "ACTIVATE_FUEL": False,
    "ACTIVATE_POSITION_ERROR": False,
    "PROBABILITY_MAP": False,
}

# The eight swept parameters and the range each is drawn over. The ranges deliberately reach past the
# calibrated defaults on the *easy* side: the no UAV baseline at the shipped values lost 100% of 5000
# runs, so a design centred on them would measure nothing but the ceiling. Lower density, slower spread,
# faster burnout and a tougher base are what give the sweep somewhere below 100% to land.
#
# Each entry is (low, high, kind); 'int' is rounded to a whole number, 'float' is left alone.
RANGES = {
    # config default 4. Steps the base survives burning for.
    "BHP": (2, 20, "int"),
    # config default 0.9. Downwind contrast; 0 is a still day.
    "MU": (0.0, 0.95, "float"),
    # config default 1. Fuel a burning cell loses per fire update: larger burns out sooner.
    "BURNING_RATE": (1, 4, "int"),
    # config default 1. Steps *between* fire updates, so larger is slower. 6 nearly freezes the fire.
    "FIRE_SPREAD_SPEED": (1, 6, "int"),
    # config default 0.9. Below ~0.5 the vegetation stops percolating and fires die out on their own.
    "DENSITY_PROB": (0.45, 1.0, "float"),
    # config default 5. See the note above on how the upper limit is derived from this.
    "FUEL_BOTTOM_LIMIT": (1, 12, "int"),
}

# the ceiling FUEL_UPPER_LIMIT is drawn up to, from FUEL_BOTTOM_LIMIT
FUEL_UPPER_CEILING = 24

# the order the Sobol dimensions are consumed in. Fixed, because changing it changes the design.
DIMENSIONS = ("BHP", "MU", "BURNING_RATE", "FIRE_SPREAD_SPEED",
              "DENSITY_PROB", "FUEL_BOTTOM_LIMIT", "FUEL_UPPER_LIMIT")


def _scale(unit, low, high, kind):
    """Map a Sobol coordinate in [0, 1) onto a range."""
    value = low + unit * (high - low)
    # round rather than floor: floor would give the top value a slice of width zero and never draw it
    return int(round(value)) if kind == "int" else float(value)


def build_arms(n_arms=N_ARMS, seed=DESIGN_SEED):
    """The design: a list of arms, each with the parameters swept and the settings they become."""
    # d=7 for the continuous dimensions; wind direction is stratified separately below
    sampler = qmc.Sobol(d=len(DIMENSIONS), scramble=True, seed=seed)
    points = sampler.random(n_arms)

    arms = []
    for index, point in enumerate(points):
        params = {}
        for position, name in enumerate(DIMENSIONS):
            if name == "FUEL_UPPER_LIMIT":
                # drawn from [bottom, ceiling], which is what makes bottom <= upper hold by construction
                bottom = params["FUEL_BOTTOM_LIMIT"]
                params[name] = _scale(point[position], bottom, FUEL_UPPER_CEILING, "int")
                continue
            low, high, kind = RANGES[name]
            params[name] = _scale(point[position], low, high, kind)

        # stratified rather than sampled: exactly n_arms/8 arms per direction. The Sobol points are
        # scrambled, so taking the direction from the index correlates it with nothing.
        direction = COMPASS[index % len(COMPASS)]
        params["WIND_DIRECTION"] = direction

        settings = dict(CONSTANTS)
        settings.update({name: value for name, value in params.items()
                         if name != "WIND_DIRECTION"})
        # the simulation reads a list; a bare string is accepted but records itself differently
        settings["WIND_DIRECTION"] = [direction]

        arms.append({
            "arm_id": index,
            "slug": slug(index, params),
            "params": params,
            "settings": settings,
        })

    return arms


def slug(index, params):
    """Filename for an arm's results. Zero padded so the directory sorts in design order."""
    return (f"{index:04d}"
            f"_bhp{params['BHP']}"
            f"_mu{params['MU']:.3f}"
            f"_br{params['BURNING_RATE']}"
            f"_fss{params['FIRE_SPREAD_SPEED']}"
            f"_den{params['DENSITY_PROB']:.3f}"
            f"_fuel{params['FUEL_BOTTOM_LIMIT']}-{params['FUEL_UPPER_LIMIT']}"
            f"_{params['WIND_DIRECTION'].lower()}")


def load(path=None):
    """Read design.json, building it first if it is not there yet."""
    path = HERE / "design.json" if path is None else pathlib.Path(path)
    if not path.exists():
        write(path)
    with open(path) as handle:
        record = json.load(handle)
    return record["arms"]


# --- writing ----------------------------------------------------------------


def write(path=None):
    path = HERE / "design.json" if path is None else pathlib.Path(path)
    arms = build_arms()
    record = {
        "design_seed": DESIGN_SEED,
        "seed_base": SEED_BASE,
        "runs_per_arm": RUNS_PER_ARM,
        "n_arms": len(arms),
        "dimensions": list(DIMENSIONS),
        "ranges": {name: list(value) for name, value in RANGES.items()},
        "fuel_upper_ceiling": FUEL_UPPER_CEILING,
        "compass": list(COMPASS),
        # tuples do not survive a JSON round trip; the settings are re-read as lists and coerced by
        # apply_overrides, which is fine for BASE_SIZE but worth knowing about
        "constants": {name: list(value) if isinstance(value, tuple) else value
                      for name, value in CONSTANTS.items()},
        "arms": [{**arm,
                  "settings": {name: list(value) if isinstance(value, tuple) else value
                               for name, value in arm["settings"].items()}}
                 for arm in arms],
    }
    with open(path, "w") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    return arms


def main():
    arms = write()

    print(f"design seed {DESIGN_SEED}   {len(arms)} arms x {RUNS_PER_ARM} runs "
          f"= {len(arms) * RUNS_PER_ARM} runs")
    print(f"written to {HERE / 'design.json'}")
    print()

    # what the design actually covers, which is the thing worth eyeballing before committing hours to it
    print(f"{'parameter':<20} {'min':>8} {'median':>8} {'max':>8}")
    for name in DIMENSIONS:
        values = np.array([arm["params"][name] for arm in arms], dtype=float)
        print(f"{name:<20} {values.min():>8.3f} {np.median(values):>8.3f} {values.max():>8.3f}")

    counts = {direction: sum(1 for arm in arms if arm["params"]["WIND_DIRECTION"] == direction)
              for direction in COMPASS}
    print()
    print("wind direction: " + ", ".join(f"{name} {count}" for name, count in counts.items()))


if __name__ == "__main__":
    main()
