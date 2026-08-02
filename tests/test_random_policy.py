"""Tests for RandomPolicy, the original behaviour of the simulator."""

# python libraries

import pytest

# own python modules

import config

from config import ACTION_STAY

from policy import RandomPolicy


@pytest.fixture
def policy():
    return RandomPolicy()


def test_returns_one_action_per_uav(policy, observation):
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(6)]
    assert len(policy.select_actions(observations)) == 6


def test_no_uavs_gives_no_actions(policy):
    assert policy.select_actions([]) == []


def test_only_emits_movement_actions(policy, observation):
    # ACTION_STAY sits outside N_ACTIONS on purpose, so the random baseline must never produce it
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(200)]
    actions = policy.select_actions(observations)
    assert set(actions) <= set(range(config.N_ACTIONS))
    assert ACTION_STAY not in actions


def test_ignores_what_the_uav_can_see(policy, observation, seed_rng):
    # the same seed must give the same actions whether or not there is fire in view
    blind = [observation(pos=(5, 5), uav_id=i) for i in range(50)]
    burning = [observation(pos=(5, 5), burning=[(5, 6), (6, 5)], uav_id=i) for i in range(50)]

    seed_rng(1)
    from_blind = policy.select_actions(blind)
    seed_rng(1)
    assert policy.select_actions(burning) == from_blind


def test_same_seed_reproduces_the_same_actions(policy, observation, seed_rng):
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(50)]

    seed_rng(42)
    first = policy.select_actions(observations)
    seed_rng(42)
    assert policy.select_actions(observations) == first


def test_different_seeds_give_different_actions(policy, observation, seed_rng):
    # with 50 draws from 4 options, matching sequences would be a 4^-50 coincidence
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(50)]

    seed_rng(1)
    first = policy.select_actions(observations)
    seed_rng(2)
    assert policy.select_actions(observations) != first


def test_uses_every_available_action(policy, observation, seed_rng):
    seed_rng(0)
    observations = [observation(pos=(5, 5), uav_id=i) for i in range(500)]
    assert set(policy.select_actions(observations)) == set(range(config.N_ACTIONS))
