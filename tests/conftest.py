"""Shared fixtures for the policy tests.

Policies consume Observation objects and nothing else, so these tests build observations directly and never
need a grid, a model or the mesa framework. That keeps them fast and independent of the simulation.
"""

# python libraries

import random

import pytest

# own python modules

import config

from sim.policy import Observation


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

    'water' and 'water_capacity' are the loads aboard, which the fuel burn is charged against. A test that
    only cares whether there is water at all can leave them alone and say has_water=True: 'water' then
    follows it, and water_fraction() answers 1.0 or 0.0 without a capacity. Pass them to say a UAV is
    carrying a part load.

    'occluded' is the cells the smoke hid. A test that wants "a burning cell this UAV cannot see" passes the
    cell in 'occluded' and leaves it out of 'burning', which is exactly what the real UAV.observe() does: an
    occluded cell appears in no other list, so it is indistinguishable from bare ground everywhere except
    here.
    """

    def _make(pos, burning=(), unburnt=(), uav_id=0, uavs=(), fuel=None, fuel_capacity=None,
              has_water=False, water=None, water_capacity=None, base_pos=None, base_cells=(),
              building_positions=(), occluded=()):
        cells = [(tuple(cell), 1) for cell in burning]
        cells += [(tuple(cell), 0) for cell in unburnt]
        if fuel is not None and fuel_capacity is None:
            fuel_capacity = float(config.UAV_FUEL)
        if water is None:
            water = 1 if has_water else 0
        return Observation(uav_id=uav_id, pos=tuple(pos), cells=cells,
                           uav_positions=[tuple(cell) for cell in uavs],
                           occluded=[tuple(cell) for cell in occluded],
                           fuel=fuel, fuel_capacity=fuel_capacity,
                           has_water=has_water, water=water, water_capacity=water_capacity,
                           base_pos=None if base_pos is None else tuple(base_pos),
                           base_cells=[tuple(cell) for cell in base_cells],
                           building_positions=[tuple(cell) for cell in building_positions])

    return _make


@pytest.fixture
def snapshot():
    """Factory that builds a FleetSnapshot without a model, the way `observation` builds one for a UAV.

    The managing system consumes FleetSnapshot objects and nothing else, so its tests build them directly
    and never need a grid, a model or mesa -- the same reasoning that keeps the policy tests fast.

    Usage:
        snapshot(uavs=[{"uav_id": 0, "pos": (5, 5), "sees_uavs": [(5, 6)]}],
                 base_cells=[(2, 2)], fire_near_base=[(4, 4)], burning_steps=1)

    Each entry of 'uavs' is a dictionary of UavReport fields; anything left out keeps a sensible default,
    so a test names only what it is actually about. Passing base_cells=None leaves the snapshot without a
    base, which is what the firefighting extension being switched off looks like.

    A UAV's occluded cells need no parameter here -- 'sees_occluded' is a UavReport field like any other and
    goes in the dictionary. 'occluded_near_base' does need one, because the base's fields are spelled out
    below; it is the cells the base's own sensor could not see through the smoke.
    """

    from sim.managing.contract import BaseReport, FleetSnapshot, UavReport

    def _make(uavs=(), step=0, grid_size=(50, 50), base_cells=((2, 2),), fire_near_base=(),
              burning_steps=0, bhp=None, destroyed=False, occluded_near_base=()):
        reports = []
        for index, fields in enumerate(uavs):
            fields = dict(fields)
            fields.setdefault("uav_id", index)
            fields.setdefault("hp", config.UAV_HP)
            fields.setdefault("water", 1)
            fields.setdefault("policy", config.DEFAULT_UAV_POLICY)
            reports.append(UavReport(**fields))

        base = None
        if base_cells is not None:
            base = BaseReport(cells=base_cells, burning_steps=burning_steps,
                              bhp=config.BHP if bhp is None else bhp,
                              destroyed=destroyed, fire_near_base=fire_near_base,
                              occluded_near_base=occluded_near_base)

        return FleetSnapshot(step=step, grid_size=grid_size, uavs=tuple(reports), base=base)

    return _make


@pytest.fixture
def sim_config():
    """Override simulation constants for one test, restored afterwards.

    Every module reads its settings through `config.` at the point of use, so setting them here reaches
    the whole simulation, policies included.

    Usage:
        sim_config(ACTIVATE_FIREFIGHTING=True, WIDTH=9, HEIGHT=9)
    """
    saved = []

    def _set(**overrides):
        for name, value in overrides.items():
            if not hasattr(config, name):
                raise KeyError(f"unknown simulation constant: {name}")
            saved.append((name, getattr(config, name)))
            setattr(config, name, value)

    yield _set

    for name, value in reversed(saved):
        setattr(config, name, value)


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
        #
        # The positioning error is pinned off for the same reason, and it is the one that bites hardest:
        # config.py ships it on with a cell of jitter, so a UAV's *measured* position wanders, and every
        # test that asks where a UAV is -- at_base(), the UAVs in view, what the sensor reports -- fails at
        # random rather than failing honestly. Nothing here seeds SYSTEM_RANDOM, so the same test passed and
        # failed between runs. Tests about the error switch it back on and say what magnitudes they want,
        # the way tests/agents/test_uav_position_error.py does.
        #
        # Smoke occlusion is pinned off for the third time over the same argument. config.py ships it on,
        # the fire here is lit at the centre on step 0, and a plume drifting over a 9x9 grid takes cells out
        # of every observation it touches -- so a test asserting what a UAV sees, which team mate is in
        # view, or what the base sensor reports would start depending on how far the fire had got. Tests
        # about the occlusion switch it back on and place the smoke themselves, the way
        # tests/agents/test_uav_smoke_occlusion.py does.
        #
        # The wind is pinned to one direction for the fourth time over the same argument. config.py ships
        # WIND_DIRECTION as a list drawn from and WIND_VARIABILITY as a step count, so a model built here
        # would get a different wind per test and turn part way through a long one -- and the fire would
        # lean somewhere new each run. A singleton list costs no draw at all (see environment.Wind), so it
        # also keeps the fixture out of the SYSTEM_RANDOM stream. Tests about the wind say what they want:
        # tests/test_wind.py drives it directly, and tests/test_fire_spread.py names a direction per case.
        settings = {"WIDTH": 9, "HEIGHT": 9, "NUM_AGENTS": 1, "BATCH_SIZE": 10_000,
                    "DENSITY_PROB": 1.0, "FIRE_START_POSITION": None, "FIRE_START_STEP": 0,
                    "ACTIVATE_POSITION_ERROR": False, "SMOKE_OCCLUDES_OBSERVATION": False,
                    "WIND_DIRECTION": ["SOUTH"]}
        settings.update(overrides)
        sim_config(**settings)

        from sim import model as wildfire_model

        return wildfire_model.WildFireModel(policy=policy)

    return _make


@pytest.fixture
def uav_speed():
    """Set config.UAV_SPEED for one test, restored afterwards.

    Policies read config.UAV_SPEED when they run, so patching the attribute here is enough to pin how far
    they ask a UAV to fly. It is the narrow form of sim_config, for the policy tests, which have no grid
    and no model to configure; tests about the movement itself go through sim_config with the rest of the
    settings a model needs.
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
