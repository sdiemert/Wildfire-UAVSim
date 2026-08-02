"""Tests for Observation, the input every policy receives."""

# own python modules

from policy import Observation


def test_flat_states_keeps_observation_order():
    # flat_states() is what MR1 and the rest of the model consume, so the order must be preserved
    obs = Observation(uav_id=0, pos=(5, 5), cells=[((4, 5), 0), ((5, 5), 1), ((6, 5), 0), ((7, 5), 1)])
    assert obs.flat_states() == [0, 1, 0, 1]


def test_burning_positions_returns_only_burning_cells():
    obs = Observation(uav_id=0, pos=(5, 5), cells=[((4, 5), 0), ((5, 6), 1), ((6, 5), 1)])
    assert obs.burning_positions() == [(5, 6), (6, 5)]


def test_burning_count_matches_burning_positions():
    obs = Observation(uav_id=0, pos=(5, 5), cells=[((4, 5), 0), ((5, 6), 1), ((6, 5), 1)])
    assert obs.burning_count() == len(obs.burning_positions()) == 2


def test_empty_view_is_reported_as_empty():
    # a UAV can see no vegetation at all, which is how the real observe() reports bare ground
    obs = Observation(uav_id=3, pos=(0, 0))
    assert obs.cells == []
    assert obs.flat_states() == []
    assert obs.burning_positions() == []
    assert obs.burning_count() == 0


def test_observation_records_which_uav_it_belongs_to():
    obs = Observation(uav_id=7, pos=(2, 9))
    assert obs.uav_id == 7
    assert obs.pos == (2, 9)


def test_cells_default_is_not_shared_between_observations():
    # a mutable default would make every Observation share one list
    first = Observation(uav_id=0, pos=(0, 0))
    second = Observation(uav_id=1, pos=(1, 1))
    first.cells.append(((0, 0), 1))
    assert second.cells == []
