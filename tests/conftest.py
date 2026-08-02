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
    """

    def _make(pos, burning=(), unburnt=(), uav_id=0):
        cells = [(tuple(cell), 1) for cell in burning]
        cells += [(tuple(cell), 0) for cell in unburnt]
        return Observation(uav_id=uav_id, pos=tuple(pos), cells=cells)

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
