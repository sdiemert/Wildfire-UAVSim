"""Tests for RandomPolicy, the original behaviour of the simulator."""

# python libraries

import pytest

# own python modules

import config

from config import ACTION_STAY

from sim.policy import RandomPolicy


@pytest.fixture
def policy():
    return RandomPolicy()


def directions(actions):
    return [action.direction for action in actions]


def speeds(actions):
    return [action.speed for action in actions]


def test_returns_one_action_per_uav(policy, observation):
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(6)]
    assert len(policy.select_actions(observations)) == 6


def test_no_uavs_gives_no_actions(policy):
    assert policy.select_actions([]) == []


@pytest.mark.verifies("POL-RND-1")
def test_only_emits_movement_actions(policy, observation):
    # ACTION_STAY sits outside N_ACTIONS on purpose, so the random baseline must never produce it
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(200)]
    chosen = set(directions(policy.select_actions(observations)))
    assert chosen <= set(range(config.N_ACTIONS))
    assert ACTION_STAY not in chosen


@pytest.mark.verifies("POL-RND-4")
def test_ignores_what_the_uav_can_see(policy, observation, seed_rng):
    # the same seed must give the same actions whether or not there is fire in view
    blind = [observation(pos=(5, 5), uav_id=i) for i in range(50)]
    burning = [observation(pos=(5, 5), burning=[(5, 6), (6, 5)], uav_id=i) for i in range(50)]

    seed_rng(1)
    from_blind = policy.select_actions(blind)
    seed_rng(1)
    assert policy.select_actions(burning) == from_blind


@pytest.mark.verifies("POL-RND-5")
def test_same_seed_reproduces_the_same_actions(policy, observation, seed_rng):
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(50)]

    seed_rng(42)
    first = policy.select_actions(observations)
    seed_rng(42)
    assert policy.select_actions(observations) == first


@pytest.mark.verifies("POL-RND-5")
def test_different_seeds_give_different_actions(policy, observation, seed_rng):
    # with 50 draws from 4 options, matching sequences would be a 4^-50 coincidence
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(50)]

    seed_rng(1)
    first = policy.select_actions(observations)
    seed_rng(2)
    assert policy.select_actions(observations) != first


@pytest.mark.verifies("POL-RND-1")
def test_uses_every_available_action(policy, observation, seed_rng):
    seed_rng(0)
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(500)]
    assert set(directions(policy.select_actions(observations))) == set(range(config.N_ACTIONS))


# --- speed ------------------------------------------------------------------


@pytest.mark.verifies("POL-RND-2")
def test_speeds_stay_within_what_a_uav_can_fly(policy, observation, uav_speed, seed_rng):
    uav_speed(4)
    seed_rng(0)
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(200)]
    assert all(1 <= speed <= 4 for speed in speeds(policy.select_actions(observations)))


@pytest.mark.verifies("POL-RND-2")
def test_every_speed_is_used_over_many_calls(policy, observation, uav_speed, seed_rng):
    uav_speed(3)
    seed_rng(0)
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(500)]
    assert set(speeds(policy.select_actions(observations))) == {1, 2, 3}


@pytest.mark.verifies("POL-RND-2")
def test_a_one_cell_fleet_always_flies_one_cell(policy, observation, uav_speed, seed_rng):
    # the original behaviour of the simulator, before speeds existed
    uav_speed(1)
    seed_rng(0)
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(50)]
    assert set(speeds(policy.select_actions(observations))) == {1}


@pytest.mark.verifies("POL-RND-3")
def test_a_grounded_fleet_is_given_zero_speed(policy, observation, uav_speed):
    uav_speed(0)
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(10)]
    assert set(speeds(policy.select_actions(observations))) == {0}
