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
        observation(pos=(5, 5), burning=[(7, 5)], unburnt=[(4, 5)])

    'burning' and 'unburnt' are cell positions. Cells the UAV cannot see are simply left out, which is how
    the real UAV.observe() reports the edges of the grid.

    'has_water', 'base_pos' and 'building_positions' belong to the firefighting extension, and keep the
    defaults they have when it is switched off.
    """

    def _make(pos, burning=(), unburnt=(), uav_id=0,
              has_water=False, base_pos=None, building_positions=()):
        cells = [(tuple(cell), 1) for cell in burning]
        cells += [(tuple(cell), 0) for cell in unburnt]
        return Observation(uav_id=uav_id, pos=tuple(pos), cells=cells,
                           has_water=has_water,
                           base_pos=None if base_pos is None else tuple(base_pos),
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
        settings = {"WIDTH": 9, "HEIGHT": 9, "NUM_AGENTS": 1, "BATCH_SIZE": 10_000}
        settings.update(overrides)
        sim_config(**settings)

        import wildfire_model

        return wildfire_model.WildFireModel(policy=policy)

    return _make


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
