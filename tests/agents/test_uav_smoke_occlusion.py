"""Tests for what a UAV can and cannot see through smoke.

Smoke was presentation only until this extension existed: config.py said so, README.md said so, and the
sweep of 2026-08-10 found -- correctly -- that turning it on changed no outcome at all. It now takes cells
out of what a UAV reports, and out of what the home base's own sensor reports, which makes it the strongest
dial on observability in the project.

Two things are worth stating up front, because both look like bugs and are neither.

  * **Everything in an occluded cell is hidden, not only the fire.** A team mate standing in smoke is not
    reported, so Observation.occupied() calls its cell clear and SuperPolicy.deconflict() can fly a UAV
    into it. Collisions through smoke are a consequence of the extension. The alternative -- hiding the
    fire but not the traffic -- would have smoke be a filter over one layer of the map rather than a cell
    the camera cannot see into, and there is no camera that works that way.

  * **An occluded cell is deliberately indistinguishable from bare ground in `cells`.** Whether there is
    anything there to burn is part of the fire state, so an observation that let the two be told apart
    would be leaking the very thing it is withholding. `Observation.occluded` is the only place the
    difference survives, and it says nothing about what is underneath.

The fixtures place smoke by setting the per cell timer directly rather than by burning a cell for long
enough to raise it. What SMOKE_PRE_DISPELLING_COUNTER does is tested nowhere here on purpose: this file is
about the plume and the occlusion, and hunting for the step at which a cell starts smoking would make every
test in it depend on the fuel it happened to draw.
"""

# python libraries

import pytest

# own python modules

import config

from sim import agents
from sim.adapters import ModelSensor
from sim.policy import SuperPolicy


# --- helpers ----------------------------------------------------------------


# turns the smoke on over the named cells and rebuilds the plume field, which is what a step would do
def raise_smoke(model, cells):
    for cell in cells:
        fire = model.fire_agent_at(cell)
        assert fire is not None, f"no Fire agent at {cell} to raise smoke from"
        fire.smoke.smoke = True
    model.update_smoke()


# puts a UAV on a named cell, without the move machinery
def place(model, uav, cell):
    model.grid.move_agent(uav, cell)


@pytest.fixture
def smoky(make_model):
    """A 15x15 model with occlusion on and a fixed southerly wind, the fire pinned into a far corner.

    The fire is lit at (14, 14) and the tests work around the middle of the grid, so nothing smokes except
    what a test asks for. The wind is fixed, so the plume is the same every time.
    """
    return make_model(NUM_AGENTS=1, WIDTH=15, HEIGHT=15,
                      ACTIVATE_SMOKE=True, SMOKE_OCCLUDES_OBSERVATION=True,
                      ACTIVATE_WIND=True, WIND_DIRECTION=["SOUTH"],
                      SMOKE_MU=0.9, SMOKE_DRIFT_RADIUS=6, SMOKE_OCCLUSION_THRESHOLD=0.5,
                      UAV_OBSERVATION_RADIUS=4, FIRE_START_POSITION=(14, 14), FIRE_START_STEP=0)


# --- the extension switched off ---------------------------------------------


def test_nothing_is_built_and_nothing_is_hidden_with_the_extension_off(make_model):
    # the fuel is off so the UAV survives long enough to be asked: this test is about the mask, and a
    # destroyed UAV has no position to observe from
    model = make_model(SMOKE_OCCLUDES_OBSERVATION=False, ACTIVATE_SMOKE=True, ACTIVATE_FUEL=False,
                       WIDTH=15, HEIGHT=15, FIRE_START_POSITION=(7, 7), FIRE_START_STEP=0)
    for _ in range(20):
        model.step()

    assert model.smoke_field is None, "a plume field was built for a run that cannot use one"
    assert not model.occluded((7, 7))
    assert model.uavs[0].observe().occluded == []


def test_a_cell_that_is_smoking_hides_nothing_until_the_extension_is_on(make_model):
    # ACTIVATE_SMOKE alone is the old behaviour: the canvas changes, the run does not
    model = make_model(ACTIVATE_SMOKE=True, SMOKE_OCCLUDES_OBSERVATION=False,
                       WIDTH=15, HEIGHT=15, FIRE_START_POSITION=(14, 14), FIRE_START_STEP=0)
    for cell in [(7, 7), (7, 8)]:
        model.fire_agent_at(cell).smoke.smoke = True
    model.update_smoke()

    place(model, model.uavs[0], (7, 7))
    observation = model.uavs[0].observe()
    assert observation.occluded == []
    assert ((7, 7), 0) in observation.cells


# --- what the smoke takes away ----------------------------------------------


def test_a_burning_cell_under_smoke_is_absent_from_what_the_uav_reports(smoky):
    uav = smoky.uavs[0]
    place(smoky, uav, (7, 7))
    burning = smoky.fire_agent_at((7, 6))
    burning.burning = True
    raise_smoke(smoky, [(7, 7)])

    observation = uav.observe()
    assert (7, 6) not in observation.burning_positions()
    assert (7, 6) not in [cell for cell, _ in observation.cells]
    assert observation.is_occluded((7, 6))


def test_an_occluded_cell_and_a_cell_with_nothing_on_it_look_the_same(smoky):
    # the crux. One model where the cell holds burning vegetation under smoke, one where the cell holds
    # nothing at all: the 'cells' a policy is given must be equal
    uav = smoky.uavs[0]
    place(smoky, uav, (7, 7))
    smoky.fire_agent_at((7, 5)).burning = True
    raise_smoke(smoky, [(7, 7)])
    under_smoke = uav.observe()

    bare = smoky.fire_agent_at((7, 5))
    smoky.grid.remove_agent(bare)
    stripped = uav.observe()

    assert (7, 5) not in [cell for cell, _ in under_smoke.cells]
    assert (7, 5) not in [cell for cell, _ in stripped.cells]


def test_the_occluded_list_says_nothing_about_what_is_under_the_smoke(smoky):
    # the anti-leak test, and the one that fails if 'occluded' is ever built from the Fire agents found on
    # the window instead of from the window itself
    uav = smoky.uavs[0]
    place(smoky, uav, (7, 7))
    smoky.grid.remove_agent(smoky.fire_agent_at((7, 6)))     # bare ground
    smoky.fire_agent_at((7, 5)).burning = True               # burning vegetation
    raise_smoke(smoky, [(7, 7)])

    occluded = uav.observe().occluded
    assert (7, 6) in occluded and (7, 5) in occluded


def test_a_team_mate_standing_in_smoke_is_not_reported(smoky):
    # the deliberate new failure mode: the deconfliction every policy relies on reads uav_positions, so a
    # UAV the smoke hid is a UAV that can be flown into
    smoky.NUM_AGENTS = 2
    watcher, hidden = smoky.uavs[0], agents.UAV(999, smoky)
    smoky.grid.place_agent(hidden, (7, 5))
    place(smoky, watcher, (7, 7))
    raise_smoke(smoky, [(7, 7)])

    observation = watcher.observe()
    assert (7, 5) not in observation.uav_positions
    assert not observation.occupied((7, 5)), "the smoke hid a team mate but the cell still reads occupied"
    assert observation.is_occluded((7, 5))


def test_an_out_building_under_smoke_is_not_reported(make_model):
    model = make_model(NUM_AGENTS=1, WIDTH=15, HEIGHT=15, ACTIVATE_FIREFIGHTING=True,
                       BASE_POSITION=(1, 1), BASE_SIZE=(1, 1), NUM_OUT_BUILDINGS=0,
                       ACTIVATE_SMOKE=True, SMOKE_OCCLUDES_OBSERVATION=True,
                       ACTIVATE_WIND=True, WIND_DIRECTION=["SOUTH"],
                       SMOKE_MU=0.9, SMOKE_DRIFT_RADIUS=6, SMOKE_OCCLUSION_THRESHOLD=0.5,
                       UAV_OBSERVATION_RADIUS=4, FIRE_START_POSITION=(14, 14), FIRE_START_STEP=0)
    building = agents.OutBuilding(998, model)
    model.grid.place_agent(building, (7, 5))
    place(model, model.uavs[0], (7, 7))
    raise_smoke(model, [(7, 7)])

    observation = model.uavs[0].observe()
    assert (7, 5) not in observation.building_positions
    assert observation.is_occluded((7, 5))


def test_a_uav_buried_in_smoke_reports_an_empty_observation(smoky):
    uav = smoky.uavs[0]
    place(smoky, uav, (7, 7))
    # the window is 9 cells on a side at radius 4, and a plume only runs SMOKE_DRIFT_RADIUS = 6 cells
    # downwind, so it takes two fronts to bury the whole of it: y 11..5 from the first, y 9..3 from the
    # second
    raise_smoke(smoky, [(x, y) for x in range(3, 12) for y in (11, 9)])

    observation = uav.observe()
    assert observation.cells == []
    assert observation.flat_states() == []
    assert observation.burning_count() == 0
    assert observation.occluded_count() == 81 == config.N_OBSERVATIONS


# --- one mask per step ------------------------------------------------------


def test_every_read_of_a_step_is_told_the_same_thing(smoky):
    # observe() runs at least twice per UAV per step -- once for the policy, once for the managing
    # system's sensor -- and a third time if anything is watching. All of them must agree, which is why
    # occlusion is a threshold on a field built once per step rather than a draw
    policy = SuperPolicy(default="firefighter")
    sensor = ModelSensor(smoky, policy)
    uav = smoky.uavs[0]

    for _ in range(6):
        first = uav.observe().occluded
        report = sensor.uav_report(uav)
        second = uav.observe().occluded

        assert first == second
        assert set(report.sees_occluded) == {tuple(cell) for cell in first}
        smoky.step()


def test_the_mask_a_step_reads_is_the_one_the_last_schedule_left(smoky):
    # update_smoke() runs after schedule.step(), because the Smoke timers tick inside Fire.step() and every
    # reader of the mask is upstream of the schedule. What that buys is the assertion below: the mask does
    # not change while a step is being taken
    raise_smoke(smoky, [(7, 11)])
    before = smoky.smoke_opaque.copy()
    place(smoky, smoky.uavs[0], (7, 7))

    during = smoky.uavs[0].observe().occluded
    assert {(x, y) for x in range(15) for y in range(15) if before[x, y]} >= set(during)


# --- what it costs the run --------------------------------------------------


def test_mr1_falls_when_the_team_cannot_see_the_fire(make_model):
    # MR1 scores what the team actually saw, so a team staring at a plume scores less. Intended: fire
    # nobody could see was not monitored
    def run(occluding):
        model = make_model(NUM_AGENTS=1, WIDTH=15, HEIGHT=15, ACTIVATE_SMOKE=True,
                           SMOKE_OCCLUDES_OBSERVATION=occluding, ACTIVATE_WIND=True,
                           WIND_DIRECTION=["SOUTH"], SMOKE_MU=0.9, SMOKE_DRIFT_RADIUS=6,
                           SMOKE_OCCLUSION_THRESHOLD=0.5, UAV_OBSERVATION_RADIUS=4,
                           FIRE_START_POSITION=(7, 7), FIRE_START_STEP=0)
        place(model, model.uavs[0], (7, 7))
        for _ in range(12):
            place(model, model.uavs[0], (7, 7))     # pinned, so the two runs watch the same ground
            model.step()
        return sum(model.MR1_LIST)

    assert run(occluding=True) < run(occluding=False)


def test_the_state_vector_keeps_its_length_when_the_smoke_takes_cells_away(smoky):
    # state() pads a short list with zeros up to N_OBSERVATIONS, so an occluded cell scores as "not
    # burning" rather than as "unknown". Pinned here so the conflation is on record: it is the same
    # padding that has always made a cell off the edge of the grid indistinguishable from an unburnt one
    place(smoky, smoky.uavs[0], (7, 7))
    raise_smoke(smoky, [(x, y) for x in range(3, 12) for y in (11, 9)])

    state = smoky.state()
    assert len(state) == 1
    assert state[0] == [0] * config.N_OBSERVATIONS


# --- the base's own sensor --------------------------------------------------


def test_the_base_sensor_cannot_see_fire_through_smoke(make_model):
    model = make_model(NUM_AGENTS=1, WIDTH=15, HEIGHT=15, ACTIVATE_FIREFIGHTING=True,
                       BASE_POSITION=(7, 7), BASE_SIZE=(1, 1), NUM_OUT_BUILDINGS=0,
                       BASE_SENSOR_RADIUS=4, ACTIVATE_SMOKE=True, SMOKE_OCCLUDES_OBSERVATION=True,
                       ACTIVATE_WIND=True, WIND_DIRECTION=["SOUTH"],
                       SMOKE_MU=0.9, SMOKE_DRIFT_RADIUS=6, SMOKE_OCCLUSION_THRESHOLD=0.5,
                       FIRE_START_POSITION=(14, 14), FIRE_START_STEP=0)
    sensor = ModelSensor(model, SuperPolicy(default="firefighter"))
    model.fire_agent_at((7, 5)).burning = True

    assert (7, 5) in sensor.base_report().fire_near_base

    raise_smoke(model, [(7, 9)])
    report = sensor.base_report()
    assert (7, 5) not in report.fire_near_base, "the base saw a fire through a plume"
    assert (7, 5) in report.occluded_near_base
