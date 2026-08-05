"""Tests for the planner that weights the home base over everything but destruction.

These are written against the heuristic planner rather than in isolation, because 'defensive' is not a
planner in its own right so much as an argument with that one about two rules. A test that only said
"defensive sends defenders" would pass for the default planner too, and would go on passing if the two ever
became the same thing -- which would quietly turn one arm of an experiment into a duplicate of another.
"""

# python libraries

import pytest

# own python modules

from sim.managing.contract import Symptoms
from sim.managing.knowledge import Knowledge
from sim.managing.plan.defensive import DefensivePlanner
from sim.managing.plan.heuristic import HeuristicPlanner


@pytest.fixture
def planners():
    return DefensivePlanner(), HeuristicPlanner()


@pytest.fixture
def no_hysteresis(sim_config):
    """Apply every decision immediately, so a test about *what* is decided is not about *when*."""
    sim_config(ADAPTATION_HYSTERESIS=1)
    return Knowledge


# what each UAV was told to fly, as {uav id: policy name}
def allocated(allocation):
    return {directive.uav_id: directive.policy for directive in allocation.directives}


def count(allocation, policy):
    return sum(1 for name in allocated(allocation).values() if name == policy)


@pytest.fixture
def fleet(snapshot):
    return snapshot(base_cells=[(0, 0)], uavs=[{"uav_id": i, "pos": (i + 1, i + 1)} for i in range(8)])


# --- more of the team goes to the base --------------------------------------


@pytest.mark.parametrize("threat", [1, 2])
def test_it_sends_more_defenders_than_the_default_planner(planners, fleet, no_hysteresis, threat):
    defensive, heuristic = planners
    symptoms = Symptoms(base_threat=threat, flying=8)

    sent = count(defensive.plan(fleet, symptoms, no_hysteresis()), "defend-base")
    assert sent > count(heuristic.plan(fleet, symptoms, no_hysteresis()), "defend-base")


def test_both_send_the_whole_team_when_the_base_is_alight(planners, fleet, no_hysteresis):
    """Level 3 means there is nothing else left worth doing, and neither planner disagrees about that."""
    for planner in planners:
        allocation = planner.plan(fleet, Symptoms(base_threat=3, flying=8), no_hysteresis())
        assert count(allocation, "defend-base") == 8


def test_a_quiet_run_is_flown_the_same_way_by_both(planners, fleet, no_hysteresis, sim_config):
    """The two only differ under pressure; with nothing wrong they are the same managing system."""
    sim_config(DEFAULT_UAV_POLICY="firefighter")
    defensive, heuristic = planners
    symptoms = Symptoms(flying=8)
    assert allocated(defensive.plan(fleet, symptoms, no_hysteresis())) \
        == allocated(heuristic.plan(fleet, symptoms, no_hysteresis()))


# --- crowding is left to SuperPolicy ----------------------------------------


def test_a_crowded_uav_keeps_its_mission(planners, fleet, no_hysteresis, sim_config):
    sim_config(DEFAULT_UAV_POLICY="firefighter")
    defensive, heuristic = planners
    symptoms = Symptoms(crowding={0: 2, 1: 3}, flying=8)

    assert count(defensive.plan(fleet, symptoms, no_hysteresis()), "disperse") == 0
    # ... which is exactly what the default planner does not do
    assert count(heuristic.plan(fleet, symptoms, no_hysteresis()), "disperse") == 2


def test_a_uav_one_collision_from_destruction_is_still_pulled_out(planners, snapshot, no_hysteresis):
    """Rule 1 is about what is irreversible, not about crowding, so this planner keeps it."""
    defensive, _ = planners
    state = snapshot(base_cells=[(0, 0)],
                     uavs=[{"uav_id": 0, "pos": (5, 5), "hp": 1}, {"uav_id": 1, "pos": (6, 6)}])
    allocation = defensive.plan(state, Symptoms(flying=2), no_hysteresis())
    assert allocated(allocation)[0] == "disperse"


def test_a_hurt_uav_is_pulled_out_even_with_the_base_burning(planners, snapshot, no_hysteresis):
    defensive, _ = planners
    state = snapshot(base_cells=[(0, 0)],
                     uavs=[{"uav_id": 0, "pos": (1, 1), "hp": 1}, {"uav_id": 1, "pos": (6, 6)}])
    allocation = defensive.plan(state, Symptoms(base_threat=3, flying=2), no_hysteresis())
    assert allocated(allocation)[0] == "disperse"
    assert allocated(allocation)[1] == "defend-base"
