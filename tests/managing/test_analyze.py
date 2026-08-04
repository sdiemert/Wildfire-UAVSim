"""Tests for the Analyse step: what the managing system makes of a reading."""

# python libraries

import pytest

# own python modules

import config

from sim.managing.analyze import HeuristicAnalyzer
from sim.managing.knowledge import Knowledge


@pytest.fixture
def analyzer():
    return HeuristicAnalyzer()


# --- the home base ----------------------------------------------------------


def test_no_fire_near_the_base_is_no_threat(analyzer, snapshot):
    assert analyzer.analyze(snapshot(uavs=[{"pos": (5, 5)}])).base_threat == 0


def test_fire_beyond_the_threat_radius_is_no_threat(analyzer, snapshot, sim_config):
    sim_config(BASE_THREAT_RADIUS=5)
    state = snapshot(base_cells=[(0, 0)], fire_near_base=[(0, 20)])
    assert analyzer.analyze(state).base_threat == 0


def test_fire_inside_the_threat_radius_raises_the_threat(analyzer, snapshot, sim_config):
    sim_config(BASE_THREAT_RADIUS=9)
    state = snapshot(base_cells=[(0, 0)], fire_near_base=[(0, 7)])
    assert analyzer.analyze(state).base_threat == 1


def test_fire_close_to_the_base_raises_it_further(analyzer, snapshot, sim_config):
    sim_config(BASE_THREAT_RADIUS=9)
    state = snapshot(base_cells=[(0, 0)], fire_near_base=[(0, 2)])
    assert analyzer.analyze(state).base_threat == 2


def test_fire_on_the_base_itself_is_the_worst_it_gets(analyzer, snapshot):
    state = snapshot(base_cells=[(5, 5)], fire_near_base=[(5, 5)])
    assert analyzer.analyze(state).base_threat == 3


def test_a_destroyed_base_is_the_worst_it_gets(analyzer, snapshot):
    assert analyzer.analyze(snapshot(destroyed=True)).base_threat == 3


def test_no_base_at_all_is_no_threat(analyzer, snapshot):
    # the firefighting extension switched off: there is nothing to defend
    state = snapshot(uavs=[{"pos": (5, 5)}], base_cells=None)
    assert analyzer.analyze(state).base_threat == 0
    assert state.base is None


# this is the regression that mattered most. BHP damage is cumulative and never repaid, so reading the
# threat off burning_steps pins it at 3 from the first point of damage onward: the managing system then
# holds the whole team over a base that stopped burning long ago while the wildfire spreads unopposed.
def test_damage_already_taken_does_not_by_itself_keep_the_threat_up(analyzer, snapshot):
    state = snapshot(base_cells=[(5, 5)], burning_steps=3, bhp=5, fire_near_base=[])
    assert analyzer.analyze(state).base_threat == 0, \
        "a base that is not currently threatened must not stay at its old threat level"


def test_damage_already_taken_does_make_a_live_threat_more_urgent(analyzer, snapshot, sim_config):
    sim_config(BASE_THREAT_RADIUS=9)
    pristine = snapshot(base_cells=[(0, 0)], fire_near_base=[(0, 7)], burning_steps=0, bhp=5)
    hurt = snapshot(base_cells=[(0, 0)], fire_near_base=[(0, 7)], burning_steps=4, bhp=5)
    assert analyzer.analyze(hurt).base_threat > analyzer.analyze(pristine).base_threat


def test_a_closing_front_counts_for_more_than_a_receding_one(analyzer, snapshot, sim_config):
    sim_config(BASE_THREAT_RADIUS=9)
    closing = snapshot(base_cells=[(0, 0)], fire_near_base=[(0, 6)])

    # Monitor records the reading before Analyse sees it, so the current snapshot is the latest entry in
    # the history and the one before it is what "closing in" is judged against
    knowledge = Knowledge()
    knowledge.record(snapshot(base_cells=[(0, 0)], fire_near_base=[(0, 8)]))
    knowledge.record(closing)

    # the same snapshot judged with and without the history that says the fire is getting closer
    assert analyzer.analyze(closing, knowledge).base_threat > analyzer.analyze(closing, None).base_threat


def test_a_receding_front_does_not_count_for_more(analyzer, snapshot, sim_config):
    sim_config(BASE_THREAT_RADIUS=9)
    receding = snapshot(base_cells=[(0, 0)], fire_near_base=[(0, 8)])

    knowledge = Knowledge()
    knowledge.record(snapshot(base_cells=[(0, 0)], fire_near_base=[(0, 6)]))
    knowledge.record(receding)

    assert analyzer.analyze(receding, knowledge).base_threat == analyzer.analyze(receding, None).base_threat


# --- crowding ---------------------------------------------------------------


def test_uavs_flying_close_together_are_reported_as_crowded(analyzer, snapshot, sim_config):
    sim_config(SECURITY_DISTANCE=3)
    state = snapshot(uavs=[{"uav_id": 0, "pos": (10, 10), "sees_uavs": [(10, 11)]},
                           {"uav_id": 1, "pos": (10, 11), "sees_uavs": [(10, 10)]}])
    assert analyzer.analyze(state).crowding == {0: 1, 1: 1}


def test_uavs_flying_apart_are_not_crowded(analyzer, snapshot, sim_config):
    sim_config(SECURITY_DISTANCE=2)
    state = snapshot(uavs=[{"uav_id": 0, "pos": (10, 10), "sees_uavs": [(10, 20)]}])
    assert analyzer.analyze(state).crowding == {}


# the home base footprint is shared airspace: any number of UAVs may sit on it without colliding, which is
# what lets the whole team launch from it and queue on it to refill. Counting that as crowding reported the
# team as being in danger on step 1 of every run, when they were all still on the pad.
def test_uavs_stacked_on_the_home_base_are_not_crowded(analyzer, snapshot, sim_config):
    sim_config(SECURITY_DISTANCE=3)
    state = snapshot(base_cells=[(2, 2), (2, 3)],
                     uavs=[{"uav_id": 0, "pos": (2, 2), "sees_uavs": [(2, 3)]},
                           {"uav_id": 1, "pos": (2, 3), "sees_uavs": [(2, 2)]}])
    assert analyzer.analyze(state).crowding == {}, \
        "the base footprint is shared airspace and UAVs cannot collide there"


def test_a_uav_off_the_base_is_not_crowded_by_one_sitting_on_it(analyzer, snapshot, sim_config):
    sim_config(SECURITY_DISTANCE=3)
    state = snapshot(base_cells=[(2, 2)], uavs=[{"uav_id": 0, "pos": (2, 3), "sees_uavs": [(2, 2)]}])
    assert analyzer.analyze(state).crowding == {}


# --- UAVs at risk -----------------------------------------------------------


def test_a_uav_on_its_last_health_point_is_at_risk(analyzer, snapshot):
    state = snapshot(uavs=[{"uav_id": 0, "pos": (5, 5), "hp": 1}, {"uav_id": 1, "pos": (9, 9), "hp": 3}])
    assert analyzer.analyze(state).at_risk == (0,)


def test_a_nearly_dry_uav_is_at_risk(analyzer, snapshot, sim_config):
    sim_config(UAV_FUEL_RESERVE=0.25)
    state = snapshot(uavs=[{"uav_id": 0, "pos": (5, 5), "fuel": 10.0, "fuel_capacity": 100.0}])
    assert analyzer.analyze(state).at_risk == (0,)


def test_attrition_is_reported(analyzer, snapshot):
    state = snapshot(uavs=[{"pos": (1, 1)}, {"pos": None, "alive": False}, {"pos": (3, 3)}])
    symptoms = analyzer.analyze(state)
    assert (symptoms.lost, symptoms.flying) == (1, 2)


# --- the short circuit ------------------------------------------------------


def test_a_healthy_fleet_needs_no_adaptation(analyzer, snapshot, sim_config):
    sim_config(SECURITY_DISTANCE=2)
    state = snapshot(uavs=[{"pos": (10, 10)}, {"pos": (20, 20)}])
    assert not analyzer.analyze(state).requires_adaptation()


@pytest.mark.parametrize("problem", [
    {"base_threat": 1},
    {"crowding": {0: 1}},
    {"at_risk": (0,)},
])
def test_anything_wrong_calls_for_adaptation(problem):
    from sim.managing.contract import Symptoms
    assert Symptoms(**problem).requires_adaptation()
