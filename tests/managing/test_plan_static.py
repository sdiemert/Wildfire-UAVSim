"""Tests for the planner that never adapts: the experimental control.

Its whole value is negative -- it is what a managed run is compared against to separate what SuperPolicy is
worth from what adapting is worth -- so what has to be true of it is that it *does not* do things. A control
arm that quietly reallocated anything would silently invalidate every comparison drawn against it, and
nothing in the results would look wrong.
"""

# python libraries

import pytest

# own python modules

from sim.managing.contract import Symptoms
from sim.managing.knowledge import Knowledge
from sim.managing.plan.static import StaticPlanner


@pytest.fixture
def planner():
    return StaticPlanner()


# what each UAV was told to fly, as {uav id: policy name}
def allocated(allocation):
    return {directive.uav_id: directive.policy for directive in allocation.directives}


# the symptoms of a run going as badly as it can: base alight, everybody crowded, everybody hurt
def emergency(count=3):
    return Symptoms(base_threat=3, threat_distance=0.0, crowding={i: 3 for i in range(count)},
                    at_risk=tuple(range(count)), flying=count)


@pytest.fixture
def fleet(snapshot):
    return snapshot(uavs=[{"uav_id": 0, "pos": (5, 5), "policy": "firefighter"},
                          {"uav_id": 1, "pos": (6, 6), "policy": "firefighter"},
                          {"uav_id": 2, "pos": (7, 7), "policy": "random"}])


# --- what it does once ------------------------------------------------------


def test_it_holds_every_uav_on_what_it_was_already_flying(planner, fleet):
    """That is what makes it a like-for-like control of the unmanaged arm, whatever --policy was passed."""
    assert allocated(planner.plan(fleet, Symptoms(flying=3), Knowledge())) == {
        0: "firefighter", 1: "firefighter", 2: "random"}


def test_it_can_be_told_to_hold_the_team_on_one_policy(fleet):
    planner = StaticPlanner(policy="defend-base")
    assert set(allocated(planner.plan(fleet, Symptoms(flying=3), Knowledge())).values()) \
        == {"defend-base"}


# --- and then never again ---------------------------------------------------


def test_it_says_nothing_on_any_evaluation_after_the_first(planner, fleet):
    planner.plan(fleet, Symptoms(flying=3), Knowledge())
    for _ in range(5):
        assert planner.plan(fleet, Symptoms(flying=3), Knowledge()).directives == ()


def test_no_emergency_makes_it_reconsider(planner, fleet):
    """The control arm has to stay a control arm on exactly the runs that are worth comparing."""
    planner.plan(fleet, Symptoms(flying=3), Knowledge())
    assert planner.plan(fleet, emergency(), Knowledge()).directives == ()


def test_a_run_of_evaluations_never_names_a_second_allocation(planner, snapshot):
    """Whatever happens to the fleet, only one allocation is ever issued."""
    issued = []
    for step in range(20):
        state = snapshot(step=step, base_cells=[(0, 0)],
                         uavs=[{"uav_id": 0, "pos": (step, step), "policy": "firefighter", "hp": 1},
                               {"uav_id": 1, "pos": (5, 5), "policy": "firefighter"}],
                         fire_near_base=[(1, 1)], burning_steps=step)
        allocation = planner.plan(state, emergency(2), Knowledge())
        if allocation.directives:
            issued.append(allocated(allocation))

    assert issued == [{0: "firefighter", 1: "firefighter"}]


# --- edges ------------------------------------------------------------------


def test_an_empty_fleet_is_not_counted_as_having_been_allocated(planner, snapshot):
    """Otherwise a run whose first evaluation lands before the team exists is never allocated at all."""
    assert planner.plan(snapshot(uavs=[]), Symptoms(), Knowledge()).directives == ()
    assert not planner.issued


def test_a_uav_that_is_gone_is_left_out(planner, snapshot):
    state = snapshot(uavs=[{"uav_id": 0, "pos": (5, 5), "policy": "firefighter"},
                           {"uav_id": 1, "pos": None, "alive": False, "policy": "firefighter"}])
    assert set(allocated(planner.plan(state, Symptoms(flying=1), Knowledge()))) == {0}


def test_it_says_why_it_did_nothing(planner, fleet):
    """The rationale is shown on the status panel, where a blank one reads as a broken managing system."""
    assert planner.plan(fleet, Symptoms(flying=3), Knowledge()).rationale
    assert planner.plan(fleet, Symptoms(flying=3), Knowledge()).rationale
