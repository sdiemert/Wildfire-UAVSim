"""Shared fixtures for the policy tests.

Policies consume Observation objects and nothing else, so these tests build observations directly and never
need a grid, a model or the mesa framework. That keeps them fast and independent of the simulation.
"""

# python libraries

import random

import pytest

# own python modules

import config

from policy import Observation


@pytest.fixture
def observation():
    """Factory that builds an Observation without a grid.

    Usage:
        observation(pos=(5, 5), burning=[(7, 5)], unburnt=[(4, 5)], uavs=[(5, 7)])

    'burning' and 'unburnt' are cell positions. Cells the UAV cannot see are simply left out, which is how
    the real UAV.observe() reports the edges of the grid.

    'uavs' is where the other UAVs in view are standing, which a policy needs to keep its team from
    colliding. It is reported whether or not the firefighting extension is switched on.

    'fuel' and 'fuel_capacity' belong to the fuel extension and are None when it is switched off, which
    is what makes low_fuel() False and lets a policy ignore fuel entirely. Passing 'fuel' alone defaults
    the capacity to config.UAV_FUEL, so a test can just say fuel=10 and mean "nearly dry".

    'has_water', 'base_pos', 'base_cells' and 'building_positions' belong to the firefighting extension,
    and keep the defaults they have when it is switched off.
    """

    def _make(pos, burning=(), unburnt=(), uav_id=0, uavs=(), fuel=None, fuel_capacity=None,
              has_water=False, base_pos=None, base_cells=(), building_positions=()):
        cells = [(tuple(cell), 1) for cell in burning]
        cells += [(tuple(cell), 0) for cell in unburnt]
        if fuel is not None and fuel_capacity is None:
            fuel_capacity = float(config.UAV_FUEL)
        return Observation(uav_id=uav_id, pos=tuple(pos), cells=cells,
                           uav_positions=[tuple(cell) for cell in uavs],
                           fuel=fuel, fuel_capacity=fuel_capacity,
                           has_water=has_water,
                           base_pos=None if base_pos is None else tuple(base_pos),
                           base_cells=[tuple(cell) for cell in base_cells],
                           building_positions=[tuple(cell) for cell in building_positions])

    return _make


@pytest.fixture
def sim_config():
    """Override simulation constants for one test, restored afterwards.

    `from config import *` copies the bindings into agents.py and wildfire_model.py, so a constant has to be
    patched in each of them. Policies read `config.` at call time and need no patching.

    Usage:
        sim_config(ACTIVATE_FIREFIGHTING=True, WIDTH=9, HEIGHT=9)
    """
    import matplotlib

    matplotlib.use("Agg", force=True)  # the model calls plt.ion() on construction

    import agents
    import wildfire_model

    modules = (config, agents, wildfire_model)
    saved = []

    def _set(**overrides):
        for name, value in overrides.items():
            if not hasattr(config, name):
                raise KeyError(f"unknown simulation constant: {name}")
            for module in modules:
                if hasattr(module, name):
                    saved.append((module, name, getattr(module, name)))
                    setattr(module, name, value)

    yield _set

    for module, name, value in reversed(saved):
        setattr(module, name, value)


@pytest.fixture
def make_model(sim_config):
    """Builds a WildFireModel after applying config overrides, on a small grid by default.

    Usage:
        model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2))
    """

    def _make(policy=None, **overrides):
        # the ignition is pinned to the centre of the grid at step 0, so that the tests do not depend on
        # whatever FIRE_START_POSITION and FIRE_START_STEP happen to be set to in config.py. Tests about
        # the ignition itself override them. The density is pinned as well, so that every cell holds a
        # Fire agent: at the shipped density a test that lights a named cell fails whenever the draw
        # happened to leave that cell bare.
        settings = {"WIDTH": 9, "HEIGHT": 9, "NUM_AGENTS": 1, "BATCH_SIZE": 10_000,
                    "DENSITY_PROB": 1.0, "FIRE_START_POSITION": None, "FIRE_START_STEP": 0}
        settings.update(overrides)
        sim_config(**settings)

        import wildfire_model

        return wildfire_model.WildFireModel(policy=policy)

    return _make


@pytest.fixture
def uav_speed():
    """Set config.UAV_SPEED for one test, restored afterwards.

    Policies read config.UAV_SPEED when they run, so patching the attribute here is enough to pin how far
    they ask a UAV to fly. UAV.move() reads the constant star-imported into agents.py instead, so tests
    about the movement itself go through sim_config.
    """
    original = config.UAV_SPEED

    def _set(speed):
        config.UAV_SPEED = speed
        return speed

    yield _set
    config.UAV_SPEED = original


@pytest.fixture
def seed_rng():
    """Replace config.SYSTEM_RANDOM with a seeded generator, restored after the test.

    Policies read config.SYSTEM_RANDOM when they run rather than importing it once, so patching the
    attribute here is enough to make any randomised policy deterministic.
    """
    original = config.SYSTEM_RANDOM

    def _seed(seed=0):
        config.SYSTEM_RANDOM = random.Random(seed)
        return config.SYSTEM_RANDOM

    yield _seed
    config.SYSTEM_RANDOM = original
