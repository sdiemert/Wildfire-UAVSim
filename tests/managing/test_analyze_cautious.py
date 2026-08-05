"""Tests for the analyser that draws every line earlier than the default one does.

Like the defensive planner, this one is written against the analyser it varies rather than in isolation:
what makes it a separate arm of an experiment is that it reports something the default one does not, at the
same distance, from the same snapshot. A test that only checked it reports threat when the base is on fire
would pass for both, and would go on passing if the difference between them were ever lost.
"""

# python libraries

import pytest

# own python modules

import config

from sim.managing.analyze import CautiousAnalyzer, HeuristicAnalyzer


@pytest.fixture
def analyzers():
    return CautiousAnalyzer(), HeuristicAnalyzer()


# a snapshot with one fire cell at a given distance due east of a single cell base
@pytest.fixture
def fire_at(snapshot):
    def _make(distance, **kwargs):
        return snapshot(base_cells=[(0, 0)], fire_near_base=[(distance, 0)],
                        uavs=[{"uav_id": 0, "pos": (20, 20)}], **kwargs)

    return _make


# --- the base is worried about sooner ---------------------------------------


def test_it_reports_threat_where_the_default_analyser_reports_none(analyzers, fire_at, sim_config):
    sim_config(BASE_THREAT_RADIUS=10)
    cautious, heuristic = analyzers
    # 12 cells out: past the radius for one of them, inside the scaled radius for the other
    state = fire_at(12)
    assert heuristic.base_threat(state) == 0
    assert cautious.base_threat(state) > 0


def test_it_raises_the_threat_sooner_as_the_fire_closes(analyzers, fire_at, sim_config):
    sim_config(BASE_THREAT_RADIUS=10)
    cautious, heuristic = analyzers
    # inside half the radius, which is level 2 for one of them and still level 1 for the other
    state = fire_at(5)
    assert heuristic.base_threat(state) == 1
    assert cautious.base_threat(state) == 2


def test_a_base_that_has_taken_some_damage_is_urgent_sooner(analyzers, fire_at, sim_config):
    sim_config(BASE_THREAT_RADIUS=10, BHP=10)
    cautious, heuristic = analyzers
    # four tenths of the BHP spent: past the cautious threshold, short of the default one
    state = fire_at(8, burning_steps=4)
    assert cautious.base_threat(state) > heuristic.base_threat(state)


def test_neither_reports_a_fire_that_is_nowhere_near(analyzers, fire_at, sim_config):
    sim_config(BASE_THREAT_RADIUS=10)
    for analyzer in analyzers:
        assert analyzer.base_threat(fire_at(40)) == 0


def test_both_report_the_worst_when_the_base_is_alight(analyzers, snapshot):
    state = snapshot(base_cells=[(0, 0)], fire_near_base=[(0, 0)],
                     uavs=[{"uav_id": 0, "pos": (5, 5)}])
    for analyzer in analyzers:
        assert analyzer.base_threat(state) == 3


# --- and so are the UAVs ----------------------------------------------------


def test_it_calls_uavs_crowded_before_the_default_analyser_does(analyzers, snapshot, sim_config):
    sim_config(SECURITY_DISTANCE=4)
    cautious, heuristic = analyzers
    # 4 cells apart: exactly the security distance, so not crowding by the default measure
    state = snapshot(uavs=[{"uav_id": 0, "pos": (10, 10), "sees_uavs": [(14, 10)]},
                           {"uav_id": 1, "pos": (14, 10), "sees_uavs": [(10, 10)]}])
    assert heuristic.crowding(state.alive(), state.base) == {}
    assert set(cautious.crowding(state.alive(), state.base)) == {0, 1}


def test_the_base_footprint_is_still_shared_airspace(analyzers, snapshot):
    """Whatever the thresholds, a team queueing on the pad is not a team in danger."""
    state = snapshot(base_cells=[(2, 2), (2, 3)],
                     uavs=[{"uav_id": 0, "pos": (2, 2), "sees_uavs": [(2, 3)]},
                           {"uav_id": 1, "pos": (2, 3), "sees_uavs": [(2, 2)]}])
    for analyzer in analyzers:
        assert analyzer.crowding(state.alive(), state.base) == {}


# --- it is the same analyser otherwise --------------------------------------


def test_it_measures_the_same_things(analyzers, snapshot, sim_config):
    """Only the thresholds move: what is looked at is a statement about the managed system, not a choice."""
    sim_config(UAV_HP=3)
    cautious, heuristic = analyzers
    state = snapshot(uavs=[{"uav_id": 0, "pos": (10, 10), "hp": 1},
                           {"uav_id": 1, "pos": (30, 30), "alive": False}])
    assert cautious.at_risk(state.alive()) == heuristic.at_risk(state.alive()) == (0,)
    assert cautious.analyze(state).lost == heuristic.analyze(state).lost == 1


def test_its_thresholds_scale_the_configured_ones_rather_than_replacing_them(analyzers, fire_at,
                                                                             sim_config):
    """BASE_THREAT_RADIUS still means something with this analyser selected, or the setting is a lie."""
    cautious, _ = analyzers
    sim_config(BASE_THREAT_RADIUS=4)
    assert cautious.base_threat(fire_at(12)) == 0        # well outside a small radius, however cautious
    sim_config(BASE_THREAT_RADIUS=20)
    assert cautious.base_threat(fire_at(12)) > 0         # well inside a large one
