"""Tests for the local heuristic planner: which UAV is told to fly what, and when."""

# python libraries

import pytest

# own python modules

import config

from sim.managing.analyze import HeuristicAnalyzer
from sim.managing.contract import Symptoms
from sim.managing.knowledge import Knowledge
from sim.managing.plan.heuristic import HeuristicPlanner


@pytest.fixture
def planner():
    return HeuristicPlanner()


@pytest.fixture
def no_hysteresis(sim_config):
    """Apply every decision immediately, so a test about *what* is decided is not about *when*."""
    sim_config(ADAPTATION_HYSTERESIS=1)
    return Knowledge()


# what each UAV was told to fly, as {uav id: policy name}
def allocated(allocation):
    return {directive.uav_id: directive.policy for directive in allocation.directives}


# --- the rules, in order of precedence ---------------------------------------


def test_a_healthy_fleet_flies_the_default_policy(planner, snapshot, no_hysteresis, sim_config):
    sim_config(DEFAULT_UAV_POLICY="firefighter")
    state = snapshot(uavs=[{"uav_id": 0, "pos": (10, 10)}, {"uav_id": 1, "pos": (20, 20)}])
    allocation = planner.plan(state, Symptoms(flying=2), no_hysteresis)
    assert allocated(allocation) == {0: "firefighter", 1: "firefighter"}


def test_crowded_uavs_are_told_to_disperse(planner, snapshot, no_hysteresis):
    state = snapshot(uavs=[{"uav_id": 0, "pos": (10, 10)}, {"uav_id": 1, "pos": (20, 20)}])
    allocation = planner.plan(state, Symptoms(crowding={0: 2}, flying=2), no_hysteresis)
    assert allocated(allocation)[0] == "disperse"
    assert allocated(allocation)[1] != "disperse"


def test_a_threatened_base_gets_defenders(planner, snapshot, no_hysteresis):
    state = snapshot(base_cells=[(0, 0)],
                     uavs=[{"uav_id": i, "pos": (i, i)} for i in range(6)])
    allocation = planner.plan(state, Symptoms(base_threat=1, flying=6), no_hysteresis)
    assert "defend-base" in allocated(allocation).values()


def test_the_number_of_defenders_scales_with_the_threat(planner, snapshot, no_hysteresis):
    state = snapshot(base_cells=[(0, 0)], uavs=[{"uav_id": i, "pos": (i, i)} for i in range(6)])

    def defenders(threat):
        allocation = planner.plan(state, Symptoms(base_threat=threat, flying=6), no_hysteresis)
        return sum(1 for name in allocated(allocation).values() if name == "defend-base")

    assert defenders(1) < defenders(2) < defenders(3) == 6


def test_defenders_are_the_uavs_nearest_the_base(planner, snapshot, no_hysteresis):
    state = snapshot(base_cells=[(0, 0)],
                     uavs=[{"uav_id": 0, "pos": (30, 30)}, {"uav_id": 1, "pos": (1, 1)},
                           {"uav_id": 2, "pos": (25, 25)}])
    allocation = planner.plan(state, Symptoms(base_threat=1, flying=3), no_hysteresis)
    assert allocated(allocation)[1] == "defend-base"
    assert allocated(allocation)[0] != "defend-base"


# losing the base ends the run and a collision does not, so defending outranks merely being crowded. An
# earlier version had it the other way round and lost runs where the whole team politely spread out while
# the base burned down underneath them.
def test_defending_the_base_outranks_being_crowded(planner, snapshot, no_hysteresis):
    state = snapshot(base_cells=[(0, 0)], uavs=[{"uav_id": 0, "pos": (1, 1)}])
    allocation = planner.plan(state, Symptoms(base_threat=3, crowding={0: 2}, flying=1), no_hysteresis)
    assert allocated(allocation) == {0: "defend-base"}


# ... but a UAV one collision from destruction is worth nothing to the base either, so it still comes out
def test_a_uav_on_its_last_health_point_is_taken_out_of_traffic_regardless(planner, snapshot,
                                                                           no_hysteresis):
    state = snapshot(base_cells=[(0, 0)], uavs=[{"uav_id": 0, "pos": (1, 1), "hp": 1}])
    allocation = planner.plan(state, Symptoms(base_threat=3, flying=1), no_hysteresis)
    assert allocated(allocation) == {0: "disperse"}


def test_a_uav_on_its_last_health_point_is_not_picked_as_a_defender(planner, snapshot, no_hysteresis):
    state = snapshot(base_cells=[(0, 0)],
                     uavs=[{"uav_id": 0, "pos": (1, 1), "hp": 1}, {"uav_id": 1, "pos": (9, 9), "hp": 3}])
    # UAV 0 is nearest the base but is about to be pulled out; the defender has to be the sound one
    allocation = planner.plan(state, Symptoms(base_threat=1, flying=2), no_hysteresis)
    assert allocated(allocation) == {0: "disperse", 1: "defend-base"}


# --- the parameters that travel with a policy --------------------------------


def test_a_dispersing_uav_is_slowed_down(planner, snapshot, no_hysteresis, sim_config):
    sim_config(MANAGING_CROWDED_SPEED_CAP=1)
    state = snapshot(uavs=[{"uav_id": 0, "pos": (10, 10)}])
    allocation = planner.plan(state, Symptoms(crowding={0: 1}, flying=1), no_hysteresis)
    assert allocation.directives[0].params["speed_cap"] == 1


def test_a_badly_damaged_uav_is_given_a_wider_berth(planner, snapshot, no_hysteresis):
    state = snapshot(uavs=[{"uav_id": 0, "pos": (10, 10), "hp": 1},
                           {"uav_id": 1, "pos": (20, 20), "hp": 3}])
    symptoms = Symptoms(crowding={0: 1, 1: 1}, flying=2)
    allocation = planner.plan(state, symptoms, no_hysteresis)
    separations = {d.uav_id: d.params["separation"] for d in allocation.directives}
    assert separations[0] > separations[1]


# --- hysteresis --------------------------------------------------------------


def test_a_one_off_decision_is_not_acted_on(planner, snapshot, sim_config):
    sim_config(ADAPTATION_HYSTERESIS=2, DEFAULT_UAV_POLICY="firefighter")
    knowledge = Knowledge()
    state = snapshot(uavs=[{"uav_id": 0, "pos": (10, 10), "policy": "firefighter"}])

    # the first evaluation wanting 'disperse' issues nothing: the UAV keeps flying what it has
    first = planner.plan(state, Symptoms(crowding={0: 1}, flying=1), knowledge)
    assert allocated(first) == {}


def test_a_decision_that_holds_is_acted_on(planner, snapshot, sim_config):
    sim_config(ADAPTATION_HYSTERESIS=2, DEFAULT_UAV_POLICY="firefighter")
    knowledge = Knowledge()
    state = snapshot(uavs=[{"uav_id": 0, "pos": (10, 10), "policy": "firefighter"}])
    symptoms = Symptoms(crowding={0: 1}, flying=1)

    planner.plan(state, symptoms, knowledge)
    second = planner.plan(state, symptoms, knowledge)
    assert allocated(second) == {0: "disperse"}


def test_wanting_something_else_in_between_starts_the_count_again(planner, snapshot, sim_config):
    sim_config(ADAPTATION_HYSTERESIS=2, DEFAULT_UAV_POLICY="firefighter")
    knowledge = Knowledge()
    state = snapshot(uavs=[{"uav_id": 0, "pos": (10, 10), "policy": "firefighter"}])

    planner.plan(state, Symptoms(crowding={0: 1}, flying=1), knowledge)   # wants disperse
    planner.plan(state, Symptoms(flying=1), knowledge)                    # wants firefighter, which it has
    third = planner.plan(state, Symptoms(crowding={0: 1}, flying=1), knowledge)
    assert allocated(third) == {}, "the streak toward disperse should have been cleared in between"


def test_restating_the_policy_a_uav_already_flies_is_never_held_back(planner, snapshot, sim_config):
    sim_config(ADAPTATION_HYSTERESIS=3, DEFAULT_UAV_POLICY="firefighter")
    knowledge = Knowledge()
    state = snapshot(uavs=[{"uav_id": 0, "pos": (10, 10), "policy": "firefighter"}])
    # there is nothing to damp: applying it changes nothing
    assert allocated(planner.plan(state, Symptoms(base_threat=0, flying=1), knowledge)) == {0: "firefighter"}


# --- edges -------------------------------------------------------------------


def test_a_team_that_has_been_wiped_out_is_planned_for_without_crashing(planner, snapshot,
                                                                       no_hysteresis):
    state = snapshot(uavs=[{"uav_id": 0, "pos": None, "alive": False}])
    allocation = planner.plan(state, Symptoms(base_threat=3), no_hysteresis)
    assert allocation.directives == ()
    assert "no UAVs" in allocation.rationale


def test_a_destroyed_uav_is_never_allocated_anything(planner, snapshot, no_hysteresis):
    state = snapshot(uavs=[{"uav_id": 0, "pos": (1, 1)}, {"uav_id": 1, "pos": None, "alive": False}])
    allocation = planner.plan(state, Symptoms(base_threat=3, flying=1), no_hysteresis)
    assert 1 not in allocated(allocation)


def test_the_plan_says_why(planner, snapshot, no_hysteresis):
    state = snapshot(base_cells=[(0, 0)], uavs=[{"uav_id": 0, "pos": (1, 1)}])
    allocation = planner.plan(state, Symptoms(base_threat=2, threat_distance=3.0, flying=1),
                              no_hysteresis)
    assert "base threat 2" in allocation.rationale
    assert "3.0 cells" in allocation.rationale


# the analyser and the planner have to agree about what a snapshot means, which only this pairing shows
def test_the_analyser_and_the_planner_work_together(snapshot, no_hysteresis, sim_config):
    sim_config(BASE_THREAT_RADIUS=9, DEFAULT_UAV_POLICY="firefighter")
    state = snapshot(base_cells=[(0, 0)], fire_near_base=[(0, 2)],
                     uavs=[{"uav_id": 0, "pos": (1, 1)}, {"uav_id": 1, "pos": (25, 25)}])
    symptoms = HeuristicAnalyzer().analyze(state, no_hysteresis)
    allocation = HeuristicPlanner().plan(state, symptoms, no_hysteresis)
    assert allocated(allocation)[0] == "defend-base", "the UAV by the threatened base should defend it"
