"""Tests for DispersePolicy: opening the gap and nothing else."""

# python libraries

import pytest

# own python modules

import config

from config import ACTION_STAY
from sim.policy import DispersePolicy, PolicyParams


@pytest.fixture
def policy():
    return DispersePolicy()


def distance(one, other):
    return ((one[0] - other[0]) ** 2 + (one[1] - other[1]) ** 2) ** 0.5


# where an action would land a UAV, so a test can check the gap actually opened
def landing(pos, action):
    if not action.is_movement():
        return tuple(pos)
    step_x, step_y = config.MOVEMENT_VECTORS[action.direction]
    return (pos[0] + step_x * action.speed, pos[1] + step_y * action.speed)


# --- when it does nothing ---------------------------------------------------


@pytest.mark.verifies("POL-DSP-1")
def test_a_uav_that_can_see_nobody_holds_position(policy, observation, sim_config):
    sim_config(SECURITY_DISTANCE=3, UAV_SPEED=3)
    assert policy.action_for(observation(pos=(5, 5))).direction == ACTION_STAY


@pytest.mark.verifies("POL-DSP-2")
def test_a_uav_already_far_enough_off_holds_position(policy, observation, sim_config):
    sim_config(SECURITY_DISTANCE=2, UAV_SPEED=3)
    assert policy.action_for(observation(pos=(5, 5), uavs=[(15, 15)])).direction == ACTION_STAY


# --- when it moves ----------------------------------------------------------


@pytest.mark.verifies("POL-DSP-3")
def test_a_crowded_uav_opens_the_gap(policy, observation, sim_config):
    sim_config(SECURITY_DISTANCE=4, UAV_SPEED=4)
    obs = observation(pos=(10, 10), uavs=[(10, 11)])
    action = policy.action_for(obs)

    assert action.is_movement()
    assert distance(landing((10, 10), action), (10, 11)) > distance((10, 10), (10, 11))


@pytest.mark.verifies("POL-DSP-3")
def test_it_flies_away_from_the_crowd_not_into_it(policy, observation, sim_config):
    sim_config(SECURITY_DISTANCE=5, UAV_SPEED=4)
    # three team mates all below it, so the way out is up
    obs = observation(pos=(10, 10), uavs=[(9, 10), (8, 10), (9, 9)])
    action = policy.action_for(obs)
    assert action.direction == config.ACTION_RIGHT, "away from the centre of mass, which is below it"


@pytest.mark.verifies("POL-DSP-4")
def test_it_never_flies_onto_a_uav_it_can_see(policy, observation, sim_config):
    sim_config(SECURITY_DISTANCE=6, UAV_SPEED=5)
    # boxed in on one side; whatever it decides, it must not land on a team mate
    obs = observation(pos=(10, 10), uavs=[(11, 10), (12, 10), (9, 10)])
    action = policy.action_for(obs)
    assert landing((10, 10), action) not in {(11, 10), (12, 10), (9, 10)}


@pytest.mark.verifies("POL-DSP-5")
def test_a_uav_exactly_on_the_centre_of_the_crowd_still_moves(policy, observation, sim_config):
    sim_config(SECURITY_DISTANCE=5, UAV_SPEED=3)
    # the centre of mass of these two is the UAV's own cell, so there is no "away" to compute
    obs = observation(pos=(10, 10), uavs=[(9, 10), (11, 10)])
    action = policy.action_for(obs)
    assert action.direction != ACTION_STAY or action.speed == 0


@pytest.mark.verifies("POL-DSP-5")
def test_the_way_out_of_the_middle_is_drawn_from_the_run_generator(policy, observation, sim_config,
                                                                   seed_rng):
    # a fixed choice would send every boxed in UAV the same way, and would not reproduce under a seed
    sim_config(SECURITY_DISTANCE=5, UAV_SPEED=3)
    obs = observation(pos=(10, 10), uavs=[(9, 10), (11, 10)])

    seen = set()
    for seed in range(20):
        seed_rng(seed)
        seen.add(policy.action_for(obs).direction)
    assert len(seen) > 1, "the direction out of the middle of a crowd is always the same one"

    seed_rng(3)
    first = policy.action_for(obs)
    seed_rng(3)
    assert policy.action_for(obs) == first


# --- the separation it is flown to ------------------------------------------


@pytest.mark.verifies("POL-DSP-6")
def test_it_aims_for_the_security_distance_by_default(policy, sim_config):
    sim_config(SECURITY_DISTANCE=4)
    assert policy.target_separation() == 4


@pytest.mark.verifies("POL-DSP-6")
def test_a_uav_can_be_allocated_a_separation_of_its_own(policy, sim_config):
    sim_config(SECURITY_DISTANCE=2)
    policy.configure(PolicyParams(separation=6))
    assert policy.target_separation() == 6


@pytest.mark.verifies("POL-DSP-6")
def test_configuring_with_no_separation_falls_back_to_the_security_distance(policy, sim_config):
    sim_config(SECURITY_DISTANCE=3)
    policy.configure(PolicyParams())
    assert policy.target_separation() == 3


@pytest.mark.verifies("POL-DSP-6")
def test_a_wider_separation_makes_a_uav_move_when_a_narrow_one_would_not(policy, observation,
                                                                        sim_config):
    sim_config(SECURITY_DISTANCE=2, UAV_SPEED=4)
    obs = observation(pos=(10, 10), uavs=[(10, 13)])

    policy.configure(PolicyParams())
    assert policy.action_for(obs).direction == ACTION_STAY

    policy.configure(PolicyParams(separation=6))
    assert policy.action_for(obs).is_movement()


# --- the team ---------------------------------------------------------------


def test_every_uav_gets_an_action(policy, observation, sim_config):
    sim_config(SECURITY_DISTANCE=3, UAV_SPEED=3)
    obs = [observation(pos=(10, 10), uavs=[(10, 11)], uav_id=0),
           observation(pos=(10, 11), uavs=[(10, 10)], uav_id=1),
           observation(pos=(30, 30), uav_id=2)]
    assert len(policy.select_actions(obs)) == 3
