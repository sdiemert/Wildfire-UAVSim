"""Tests for the messages that cross the managed/managing boundary.

The round trip tests are the important ones here. Every message has to survive being turned into JSON and
back unchanged, because that equality *is* the contract the remote planner is written against: a planner on
the other side of a socket sees exactly what a local one sees only if nothing is lost on the way there and
back. See sim/managing/plan/remote.py.
"""

# python libraries

import dataclasses
import json

import pytest

# own python modules

from sim.managing.contract import Allocation, BaseReport, FleetSnapshot, Symptoms, UavDirective, UavReport


# a message is only safe to keep in the Knowledge base, and to hand to a planner, if it cannot be changed
@pytest.mark.parametrize("message", [
    UavReport(uav_id=0),
    BaseReport(cells=[(1, 1)]),
    FleetSnapshot(),
    Symptoms(),
    UavDirective(uav_id=0, policy="random"),
    Allocation(),
])
def test_every_message_is_frozen(message):
    assert dataclasses.is_dataclass(message)
    with pytest.raises(dataclasses.FrozenInstanceError):
        object.__setattr__  # sanity: we are testing the dataclass, not the attribute
        setattr(message, dataclasses.fields(message)[0].name, None)


# --- round trips ------------------------------------------------------------


def round_trip(message):
    """Send a message through JSON exactly as the remote planner would, and read it back."""
    return type(message).from_json(json.loads(json.dumps(message.to_json())))


def test_a_uav_report_survives_the_wire():
    report = UavReport(uav_id=3, pos=(4, 5), hp=2, water=1, policy="firefighter",
                       params={"speed_cap": 2}, fuel=12.5, fuel_capacity=150.0,
                       sees_fire=[(6, 6), (7, 7)], sees_uavs=[(4, 6)], sees_buildings=[(1, 1)])
    assert round_trip(report) == report


def test_a_base_report_survives_the_wire():
    base = BaseReport(cells=[(2, 2), (2, 3)], burning_steps=2, bhp=5, destroyed=False,
                      serving=1, fire_near_base=[(3, 3)])
    assert round_trip(base) == base


def test_a_whole_snapshot_survives_the_wire(snapshot):
    original = snapshot(uavs=[{"pos": (5, 5), "sees_fire": [(6, 6)]},
                              {"pos": (9, 9), "alive": False}],
                        step=17, fire_near_base=[(3, 3)], burning_steps=1)
    assert round_trip(original) == original


def test_symptoms_survive_the_wire():
    symptoms = Symptoms(base_threat=2, threat_distance=3.5, crowding={0: 2, 1: 1},
                        at_risk=(3,), lost=1, flying=4)
    assert round_trip(symptoms) == symptoms


def test_an_allocation_survives_the_wire():
    allocation = Allocation(step=9, rationale="because", directives=(
        UavDirective(uav_id=0, policy="defend-base"),
        UavDirective(uav_id=1, policy="disperse", params={"separation": 3, "speed_cap": 1}),
    ))
    assert round_trip(allocation) == allocation


# infinity is not valid JSON, so an unthreatened base has to travel as something else and come back
def test_an_unreachable_threat_distance_survives_the_wire():
    symptoms = Symptoms(base_threat=0, threat_distance=float("inf"))
    assert json.dumps(symptoms.to_json())  # would raise ValueError for a bare float('inf')
    assert round_trip(symptoms).threat_distance == float("inf")


# JSON has no integer keys, so a mapping keyed by UAV id comes back keyed by strings unless it is put back
def test_crowding_keys_come_back_as_uav_ids():
    symptoms = round_trip(Symptoms(crowding={7: 3}))
    assert symptoms.crowding == {7: 3}
    assert all(isinstance(key, int) for key in symptoms.crowding)


# --- normalisation ----------------------------------------------------------


# a snapshot built from lists, as JSON produces, must equal one built from tuples, as a test writes
def test_positions_are_normalised_so_lists_and_tuples_agree():
    from_lists = UavReport(uav_id=0, pos=[3, 4], sees_fire=[[5, 5]])
    from_tuples = UavReport(uav_id=0, pos=(3, 4), sees_fire=((5, 5),))
    assert from_lists == from_tuples
    assert from_lists.pos == (3, 4)


# --- the helpers a planner reads them through -------------------------------


def test_a_snapshot_reports_only_the_uavs_still_flying(snapshot):
    state = snapshot(uavs=[{"pos": (1, 1)}, {"pos": (2, 2), "alive": False}, {"pos": (3, 3)}])
    assert len(state.uavs) == 3          # a destroyed UAV is still reported, so attrition is visible
    assert len(state.alive()) == 2       # but it is not something to allocate anything to


def test_known_fire_is_everything_anybody_can_see(snapshot):
    state = snapshot(uavs=[{"pos": (5, 5), "sees_fire": [(6, 6)]},
                           {"pos": (8, 8), "sees_fire": [(6, 6), (9, 9)]}],
                     fire_near_base=[(3, 3)])
    # the duplicate (6, 6) is counted once, and the base's own sensor contributes (3, 3)
    assert state.known_fire() == {(6, 6), (9, 9), (3, 3)}


def test_the_base_reports_how_far_the_nearest_fire_is():
    base = BaseReport(cells=[(5, 5)], fire_near_base=[(5, 8), (5, 6)])
    assert base.nearest_fire_distance() == 1.0


def test_a_base_that_can_see_no_fire_is_infinitely_far_from_it():
    assert BaseReport(cells=[(5, 5)]).nearest_fire_distance() == float("inf")


def test_damage_is_reported_as_a_fraction_of_what_the_base_survives():
    assert BaseReport(cells=[(1, 1)], burning_steps=3, bhp=5).damage_fraction() == pytest.approx(0.6)


def test_fuel_reads_as_a_full_tank_when_it_is_not_being_tracked():
    # so a planner that reads it plans the same way it would have before the fuel extension existed
    assert UavReport(uav_id=0, fuel=None).fuel_fraction() == 1.0


def test_an_allocation_summarises_what_it_asks_for():
    allocation = Allocation(directives=(UavDirective(0, "disperse"), UavDirective(1, "disperse"),
                                        UavDirective(2, "firefighter")))
    assert allocation.counts() == {"disperse": 2, "firefighter": 1}
    assert allocation.for_uav(2).policy == "firefighter"
    assert allocation.for_uav(99) is None
