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


# --- the other UAVs in view -------------------------------------------------


def test_uav_positions_default_to_an_empty_view():
    obs = Observation(uav_id=0, pos=(5, 5))
    assert obs.uav_positions == []
    assert not obs.occupied((5, 5))


def test_occupied_finds_the_cells_other_uavs_are_standing_on():
    obs = Observation(uav_id=0, pos=(5, 5), uav_positions=[(6, 5), (5, 8)])
    assert obs.occupied((6, 5))
    assert obs.occupied((5, 8))
    assert not obs.occupied((4, 5))
    # a UAV is never reported as standing on itself, so its own cell reads as clear
    assert not obs.occupied((5, 5))


def test_occupied_accepts_a_list_as_well_as_a_tuple():
    obs = Observation(uav_id=0, pos=(5, 5), uav_positions=[[6, 5]])
    assert obs.occupied((6, 5))


def test_uav_positions_default_is_not_shared_between_observations():
    first = Observation(uav_id=0, pos=(0, 0))
    second = Observation(uav_id=1, pos=(1, 1))
    first.uav_positions.append((2, 2))
    assert second.uav_positions == []


# --- the home base footprint ------------------------------------------------


def test_the_footprint_is_empty_without_a_base():
    obs = Observation(uav_id=0, pos=(5, 5))
    assert obs.base_footprint() == []
    assert not obs.at_base()


def test_the_anchor_alone_is_the_footprint_when_no_cells_are_given():
    # how an Observation built by hand, or by a caller that predates the footprint, reports the base
    obs = Observation(uav_id=0, pos=(1, 1), base_pos=(1, 1))
    assert obs.base_footprint() == [(1, 1)]
    assert obs.at_base()


def test_a_uav_on_any_cell_of_the_footprint_is_at_the_base():
    footprint = [(2, 2), (3, 2), (2, 3), (3, 3)]
    for cell in footprint:
        obs = Observation(uav_id=0, pos=cell, base_pos=(2, 2), base_cells=footprint)
        assert obs.at_base(), f"{cell} is part of the base"

    outside = Observation(uav_id=0, pos=(4, 2), base_pos=(2, 2), base_cells=footprint)
    assert not outside.at_base()
