"""Tests for DefendBasePolicy: fighting the fire that threatens the base rather than the nearest fire."""

# python libraries

import pytest

# own python modules

import config

from config import ACTION_DUMP_WATER, ACTION_STAY
from sim.policy import DefendBasePolicy


@pytest.fixture
def policy():
    return DefendBasePolicy()


@pytest.fixture(autouse=True)
def firefighting(sim_config):
    # this policy only means anything with the firefighting extension on, and reads WATER_DROP_RADIUS and
    # BASE_THREAT_RADIUS, so both are pinned rather than left to whatever config.py happens to say
    sim_config(ACTIVATE_FIREFIGHTING=True, WATER_DROP_RADIUS=2, BASE_THREAT_RADIUS=10, UAV_SPEED=3)


# --- what it goes for -------------------------------------------------------


# the whole point of this policy: `firefighter` would send the UAV at the fire under its nose, which is the
# wrong call when the job is keeping one building standing
@pytest.mark.verifies("POL-DEF-1")
def test_it_goes_for_the_fire_nearest_the_base_not_the_nearest_fire(policy, observation):
    obs = observation(pos=(10, 10), burning=[(11, 10), (3, 3)], has_water=True,
                      base_pos=(2, 2), base_cells=[(2, 2)])
    action, target = policy.action_for(obs)
    # (11, 10) is one cell away from the UAV; (3, 3) is what is about to burn the base down
    assert target == (3, 3)


@pytest.mark.verifies("POL-DEF-3")
def test_it_dumps_when_the_threatening_fire_is_in_range(policy, observation):
    obs = observation(pos=(3, 3), burning=[(3, 4)], has_water=True, base_pos=(2, 2), base_cells=[(2, 2)])
    action, _ = policy.action_for(obs)
    assert action.direction == ACTION_DUMP_WATER


@pytest.mark.verifies("POL-DEF-3")
def test_it_flies_at_a_threatening_fire_that_is_out_of_range(policy, observation):
    obs = observation(pos=(12, 3), burning=[(3, 3)], has_water=True, base_pos=(2, 2), base_cells=[(2, 2)])
    action, _ = policy.action_for(obs)
    assert action.is_movement()
    assert action.direction == config.ACTION_LEFT


@pytest.mark.verifies("POL-DEF-2")
def test_fire_too_far_from_the_base_is_ignored(policy, observation, sim_config):
    sim_config(BASE_THREAT_RADIUS=3)
    obs = observation(pos=(30, 30), burning=[(31, 30)], has_water=True,
                      base_pos=(2, 2), base_cells=[(2, 2)])
    action, target = policy.action_for(obs)
    assert target is None, "a fire 40 cells from the base is not this policy's problem"


@pytest.mark.verifies("POL-DEF-4")
def test_with_nothing_threatening_it_holds_station_over_the_base(policy, observation):
    obs = observation(pos=(2, 2), has_water=True, base_pos=(2, 2), base_cells=[(2, 2)])
    action, _ = policy.action_for(obs)
    assert action.direction == ACTION_STAY


@pytest.mark.verifies("POL-DEF-4")
def test_with_nothing_threatening_it_flies_home(policy, observation):
    obs = observation(pos=(9, 2), has_water=True, base_pos=(2, 2), base_cells=[(2, 2)])
    action, _ = policy.action_for(obs)
    assert action.is_movement() and action.direction == config.ACTION_LEFT


# --- the loop it shares with firefighter ------------------------------------


@pytest.mark.verifies("POL-DEF-5", "POL-DEF-10")
def test_an_empty_uav_goes_home_to_refill(policy, observation):
    obs = observation(pos=(9, 2), burning=[(3, 3)], has_water=False,
                      base_pos=(2, 2), base_cells=[(2, 2)])
    action, target = policy.action_for(obs)
    assert target is None
    assert action.direction == config.ACTION_LEFT


@pytest.mark.verifies("POL-DEF-6", "POL-DEF-10")
def test_the_fuel_reserve_outranks_the_defending(policy, observation, sim_config):
    sim_config(ACTIVATE_FUEL=True, UAV_FUEL_RESERVE=0.25)
    obs = observation(pos=(9, 2), burning=[(3, 3)], has_water=True, fuel=10, fuel_capacity=150,
                      base_pos=(2, 2), base_cells=[(2, 2)])
    action, target = policy.action_for(obs)
    assert target is None, "a UAV that would not survive the trip breaks off for home"


@pytest.mark.verifies("POL-DEF-7")
def test_it_waits_on_the_base_rather_than_leaving_mid_refill(policy, observation):
    # leaving as soon as it landed would mean never staying the steps it takes to be served
    obs = observation(pos=(2, 2), has_water=False, base_pos=(2, 2), base_cells=[(2, 2)])
    action, _ = policy.action_for(obs)
    assert action.direction == ACTION_STAY


# --- as a team --------------------------------------------------------------


@pytest.mark.verifies("POL-DEF-9")
def test_two_uavs_are_not_sent_to_the_same_fire(policy, observation):
    burning = [(3, 3), (3, 4)]
    obs = [observation(pos=(10, 10), burning=burning, has_water=True, uav_id=0,
                       base_pos=(2, 2), base_cells=[(2, 2)]),
           observation(pos=(11, 11), burning=burning, has_water=True, uav_id=1,
                       base_pos=(2, 2), base_cells=[(2, 2)])]
    _, first = policy.action_for(obs[0])
    _, second = policy.action_for(obs[1], claimed={first})
    assert first != second


@pytest.mark.verifies("POL-DEF-1")
def test_the_whole_team_converges_on_the_same_front(policy, observation):
    # each UAV is somewhere different, and they all pick fire near the base rather than fire near themselves
    burning = [(3, 3), (3, 4), (3, 5), (20, 20), (25, 25)]
    targets = []
    for uav_id, pos in enumerate([(20, 20), (25, 25), (9, 9)]):
        _, target = policy.action_for(observation(pos=pos, burning=burning, has_water=True, uav_id=uav_id,
                                                  base_pos=(2, 2), base_cells=[(2, 2)]))
        targets.append(target)
    assert all(target in [(3, 3), (3, 4), (3, 5)] for target in targets), targets


# --- without a base ---------------------------------------------------------


@pytest.mark.verifies("POL-DEF-8")
def test_with_no_base_there_is_nothing_to_defend(policy, observation):
    # the firefighting extension off: every UAV simply holds position
    obs = observation(pos=(5, 5), burning=[(6, 5)], has_water=True)
    action, target = policy.action_for(obs)
    assert target is None
    assert action.direction == ACTION_STAY


def test_it_handles_a_uav_that_sees_nothing(policy, observation):
    assert policy.select_actions([observation(pos=(5, 5))]) is not None
