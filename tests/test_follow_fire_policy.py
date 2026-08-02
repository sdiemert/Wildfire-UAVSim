"""Tests for FollowFirePolicy.

Direction reminder, from the movement vectors in UAV.move():
    ACTION_RIGHT  x + 1        ACTION_LEFT  x - 1
    ACTION_UP     y + 1        ACTION_DOWN  y - 1
"""

# python libraries

import pytest

# own python modules

from config import ACTION_DOWN, ACTION_LEFT, ACTION_RIGHT, ACTION_STAY, ACTION_UP

from policy import FollowFirePolicy


@pytest.fixture
def policy():
    return FollowFirePolicy()


# --- holding position -------------------------------------------------------


def test_holds_position_when_nothing_is_visible(policy, observation):
    # a UAV over ground with no vegetation in range sees no cells at all
    assert policy.select_actions([observation(pos=(5, 5))]) == [ACTION_STAY]


def test_holds_position_when_no_visible_cell_is_burning(policy, observation):
    obs = observation(pos=(5, 5), unburnt=[(4, 5), (6, 5), (5, 4), (5, 6)])
    assert policy.select_actions([obs]) == [ACTION_STAY]


def test_holds_position_when_already_over_the_fire(policy, observation):
    # the UAV's own cell is burning, so the nearest fire is at distance zero
    obs = observation(pos=(5, 5), burning=[(5, 5)], unburnt=[(6, 5)])
    assert policy.select_actions([obs]) == [ACTION_STAY]


# --- moving toward a single fire -------------------------------------------


@pytest.mark.parametrize(
    "fire, expected",
    [
        ((8, 5), ACTION_RIGHT),
        ((2, 5), ACTION_LEFT),
        ((5, 8), ACTION_UP),
        ((5, 2), ACTION_DOWN),
    ],
)
def test_moves_toward_fire_on_each_axis(policy, observation, fire, expected):
    obs = observation(pos=(5, 5), burning=[fire])
    assert policy.select_actions([obs]) == [expected]


def test_moves_one_cell_at_a_time(policy, observation):
    # a distant fire still produces a single step, not a jump
    obs = observation(pos=(0, 0), burning=[(9, 0)])
    assert policy.select_actions([obs]) == [ACTION_RIGHT]


# --- choosing between several fires ----------------------------------------


def test_targets_the_nearest_burning_cell(policy, observation):
    # one cell to the right, a cluster further to the left: the near one wins
    obs = observation(pos=(5, 5), burning=[(6, 5), (1, 5), (0, 5), (1, 6)])
    assert policy.select_actions([obs]) == [ACTION_RIGHT]


def test_ignores_unburnt_cells_when_choosing_a_target(policy, observation):
    # the closest cell overall is unburnt and to the left; the fire is further away to the right
    obs = observation(pos=(5, 5), burning=[(9, 5)], unburnt=[(4, 5), (3, 5)])
    assert policy.select_actions([obs]) == [ACTION_RIGHT]


def test_closes_the_larger_gap_first(policy, observation):
    # dx = 3, dy = 1, so the horizontal gap is closed first
    obs = observation(pos=(5, 5), burning=[(8, 6)])
    assert policy.select_actions([obs]) == [ACTION_RIGHT]

    # dy = 4, dx = 1, so now the vertical gap is closed first
    obs = observation(pos=(5, 5), burning=[(6, 9)])
    assert policy.select_actions([obs]) == [ACTION_UP]


# --- diagonal tie breaking --------------------------------------------------


def test_diagonal_target_picks_one_of_the_two_valid_axes(policy, observation):
    obs = observation(pos=(5, 5), burning=[(7, 7)])
    assert policy.select_actions([obs])[0] in (ACTION_RIGHT, ACTION_UP)


def test_diagonal_tie_break_is_random_not_fixed(policy, observation, seed_rng):
    # an equal gap on both axes must not always resolve the same way, otherwise every UAV would drift
    # along the same diagonal
    obs = observation(pos=(5, 5), burning=[(7, 7)])
    seen = set()
    for seed in range(20):
        seed_rng(seed)
        seen.add(policy.select_actions([obs])[0])
    assert seen == {ACTION_RIGHT, ACTION_UP}


def test_diagonal_tie_break_is_reproducible_under_a_seed(policy, observation, seed_rng):
    obs = observation(pos=(5, 5), burning=[(3, 3)])

    seed_rng(7)
    first = policy.select_actions([obs] * 10)
    seed_rng(7)
    assert policy.select_actions([obs] * 10) == first
    assert set(first) <= {ACTION_LEFT, ACTION_DOWN}


# --- multiple UAVs ----------------------------------------------------------


def test_returns_one_action_per_uav_in_order(policy, observation):
    observations = [
        observation(pos=(5, 5), burning=[(8, 5)], uav_id=0),   # fire to the right
        observation(pos=(5, 5), uav_id=1),                     # sees nothing
        observation(pos=(5, 5), burning=[(5, 1)], uav_id=2),   # fire below
    ]
    assert policy.select_actions(observations) == [ACTION_RIGHT, ACTION_STAY, ACTION_DOWN]


def test_no_uavs_gives_no_actions(policy):
    assert policy.select_actions([]) == []
