"""Tests for the two adapters that join the managing system to the simulation.

These are the only tests that need a real model, because the adapters are the only code that touches both
halves. Everything on the managing side is tested against hand built snapshots instead.
"""

# python libraries

import pytest

# own python modules

import config

from sim.adapters import AllocationEffector, ModelSensor
from sim.managing.contract import Allocation, UavDirective
from sim.policy import PolicyParams, SuperPolicy


@pytest.fixture
def managed(make_model):
    """A small model flying a SuperPolicy, with the sensor and effector wired over it."""
    policy = SuperPolicy(default="firefighter")
    model = make_model(policy=policy, NUM_AGENTS=3, WIDTH=15, HEIGHT=15,
                       ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(3, 3), BASE_SIZE=(1, 1),
                       FIRE_START_POSITION=(10, 10), FIRE_START_STEP=0)
    return model, policy, ModelSensor(model, policy), AllocationEffector(policy, model)


# --- the sensor -------------------------------------------------------------


def test_the_snapshot_reports_every_uav(managed):
    model, _, sensor, _ = managed
    assert len(sensor.read().uavs) == len(model.uavs) == 3


def test_the_snapshot_reports_where_each_uav_is(managed):
    model, _, sensor, _ = managed
    positions = {report.uav_id: report.pos for report in sensor.read().uavs}
    assert positions == {uav.unique_id: uav.pos for uav in model.uavs}


# the loop is only closed if the managing system is told the effect of its own last decision
def test_the_snapshot_reports_what_each_uav_is_currently_flying(managed):
    model, policy, sensor, _ = managed
    policy.assign(model.uavs[0].unique_id, "disperse", PolicyParams(separation=3))

    reports = {report.uav_id: report for report in sensor.read().uavs}
    assert reports[model.uavs[0].unique_id].policy == "disperse"
    assert reports[model.uavs[0].unique_id].params["separation"] == 3
    # a UAV that has been allocated nothing reports the default it is actually flying
    assert reports[model.uavs[1].unique_id].policy == "firefighter"


def test_a_destroyed_uav_is_still_reported(managed):
    model, _, sensor, _ = managed
    doomed = model.uavs[0]
    doomed.take_damage(config.UAV_HP)
    model.destroy_uav(doomed)

    report = sensor.read().by_id(doomed.unique_id)
    assert report is not None, "attrition is something the managing system needs to see"
    assert report.alive is False
    assert report.pos is None


def test_the_snapshot_only_reports_what_the_uavs_can_see(managed, sim_config):
    model, _, sensor, _ = managed
    # a fire far from every UAV and outside the base sensor is invisible to the managing system
    sim_config(BASE_SENSOR_RADIUS=1)
    sensor._sensed_cells = (None, ())    # the cache is keyed on the base, which has not changed

    far = model.fire_agent_at((14, 14))
    far.burning = True
    snapshot = sensor.read()
    assert (14, 14) not in snapshot.known_fire() or any(
        (14, 14) in report.sees_fire for report in snapshot.uavs), \
        "fire is only known if some UAV or the base sensor can actually see it"


def test_the_base_sensor_sees_fire_no_uav_is_near(managed, sim_config):
    model, _, sensor, _ = managed
    sim_config(BASE_SENSOR_RADIUS=4)
    sensor._sensed_cells = (None, ())

    # light a cell near the base; no UAV need be anywhere near it
    model.fire_agent_at((5, 3)).burning = True
    assert (5, 3) in sensor.read().base.fire_near_base


def test_the_base_is_reported_with_its_damage(managed):
    model, _, sensor, _ = managed
    model.base.burning_steps = 2

    base = sensor.read().base
    assert base.burning_steps == 2
    assert base.bhp == config.BHP
    assert set(base.cells) == set(model.base.cells)


def test_there_is_no_base_report_without_the_firefighting_extension(make_model):
    policy = SuperPolicy(default="random")
    model = make_model(policy=policy, NUM_AGENTS=1, ACTIVATE_FIREFIGHTING=False)
    assert ModelSensor(model, policy).read().base is None


# --- the effector, which is a trust boundary --------------------------------


def test_a_valid_directive_is_applied(managed):
    model, policy, _, effector = managed
    uav_id = model.uavs[0].unique_id

    applied = effector.apply(Allocation(directives=(UavDirective(uav_id, "disperse"),)))
    assert applied == 1
    assert policy.allocated(uav_id)[0] == "disperse"


def test_parameters_are_applied_with_it(managed):
    model, policy, _, effector = managed
    uav_id = model.uavs[0].unique_id

    effector.apply(Allocation(directives=(
        UavDirective(uav_id, "disperse", {"separation": 4, "speed_cap": 1}),)))
    assert policy.allocated(uav_id)[1] == PolicyParams(separation=4, speed_cap=1)


# every one of these is something a buggy planner, or a server answering for a different run, could send.
# None of them may end the run: the point is that a managing system which has gone wrong costs a run its
# adaptation quality, not its completion.
@pytest.mark.parametrize("directive, reason", [
    (UavDirective(99999, "disperse"), "no such UAV"),
    (UavDirective(0, "no-such-policy"), "a policy the simulation does not have"),
    (UavDirective(0, "disperse", {"speed_cap": -1}), "a negative speed cap"),
    (UavDirective(0, "disperse", {"separation": -3}), "a negative separation"),
    (UavDirective(0, "disperse", {"fuel_reserve": 5.0}), "a reserve outside [0, 1]"),
])
def test_a_bad_directive_is_refused_rather_than_raised(managed, directive, reason):
    model, policy, _, effector = managed
    # aim the id-valid cases at a real UAV
    if directive.uav_id == 0:
        directive = UavDirective(model.uavs[0].unique_id, directive.policy, directive.params)
    before = policy.assignment()

    applied = effector.apply(Allocation(directives=(directive,)))

    assert applied == 0, reason
    assert effector.rejected == 1
    assert policy.assignment() == before, "a refused directive must change nothing"


def test_a_directive_for_a_destroyed_uav_is_refused(managed):
    model, policy, _, effector = managed
    doomed = model.uavs[0]
    doomed.take_damage(config.UAV_HP)
    model.destroy_uav(doomed)

    assert effector.apply(Allocation(directives=(UavDirective(doomed.unique_id, "disperse"),))) == 0


def test_the_good_directives_in_a_mixed_allocation_are_still_applied(managed):
    model, policy, _, effector = managed
    good = model.uavs[1].unique_id

    applied = effector.apply(Allocation(directives=(
        UavDirective(99999, "disperse"),          # refused
        UavDirective(good, "defend-base"),        # applied
        UavDirective(good, "not-a-policy"),       # refused
    )))

    assert applied == 1
    assert policy.allocated(good)[0] == "defend-base"
    assert effector.rejected == 2


def test_an_empty_allocation_applies_nothing(managed):
    _, _, _, effector = managed
    assert effector.apply(Allocation()) == 0
