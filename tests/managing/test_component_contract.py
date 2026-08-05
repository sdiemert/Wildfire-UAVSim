"""What every MAPE-K component must do, whichever one it is.

This is the managing system's equivalent of tests/policy/test_policy_interface.py: it is parametrised over
the registries, so a component added to one of them is held to this the moment it is registered, without
anybody remembering to write a test. What is checked is the contract the rest of the loop relies on --
that a planner answers with an Allocation naming policies that exist, that an analyser answers with
Symptoms, and that neither falls over on the snapshots a real run produces at its edges: an empty fleet, a
fleet that has been wiped out, no home base at all.

The point is not that these are hard cases. It is that they happen in ordinary runs -- the first evaluation
lands before the fire starts, the last one after the team is gone, and the firefighting extension can be
switched off entirely -- and a component that only works on the comfortable ones takes a whole run down
with it, from inside mesa's step loop.
"""

# python libraries

import pytest

# own python modules

import config

from sim.managing import ANALYZERS, PLANNERS
from sim.managing.contract import Allocation, Symptoms
from sim.managing.knowledge import Knowledge
from sim.policy import POLICIES

ANALYZER_NAMES = ANALYZERS.names()
PLANNER_NAMES = PLANNERS.names()


# the snapshots any component has to survive, named so a failure says which one it was
@pytest.fixture
def situations(snapshot):
    return {
        "a healthy fleet": snapshot(uavs=[{"uav_id": i, "pos": (i * 5, i * 5)} for i in range(4)]),
        "an empty fleet": snapshot(uavs=[]),
        "a fleet that is gone": snapshot(uavs=[{"uav_id": 0, "pos": None, "alive": False}]),
        "no home base": snapshot(base_cells=None, uavs=[{"uav_id": 0, "pos": (5, 5)}]),
        "the base alight": snapshot(base_cells=[(0, 0)], fire_near_base=[(0, 0)], burning_steps=3,
                                    uavs=[{"uav_id": 0, "pos": (1, 1)}, {"uav_id": 1, "pos": (9, 9)}]),
        "everybody hurt and crowded": snapshot(
            uavs=[{"uav_id": i, "pos": (5, 5), "hp": 1, "sees_uavs": [(5, 6)]} for i in range(3)]),
        "a uav with nowhere reported": snapshot(uavs=[{"uav_id": 0, "pos": None}]),
    }


# hysteresis is what holds a first decision back, and a planner tested through it issues nothing at all --
# which would make every assertion below run over an empty list and pass without checking anything. The
# damping has its own tests; these are about what a planner decides, so they see the decisions.
def settled():
    return Knowledge(hysteresis=1)


def symptoms_for(situation):
    return Symptoms(base_threat=3, threat_distance=0.0,
                    crowding={report.uav_id: 2 for report in situation.alive()},
                    at_risk=tuple(report.uav_id for report in situation.alive()),
                    flying=len(situation.alive()))


# --- analysers --------------------------------------------------------------


@pytest.mark.parametrize("name", ANALYZER_NAMES)
def test_an_analyser_answers_with_symptoms(name, situations):
    analyzer = ANALYZERS.build(name)
    for description, situation in situations.items():
        assert isinstance(analyzer.analyze(situation, settled()), Symptoms), description


@pytest.mark.parametrize("name", ANALYZER_NAMES)
def test_an_analyser_works_without_a_knowledge_base(name, situations):
    """The remote fallback and several tests analyse a snapshot on its own."""
    analyzer = ANALYZERS.build(name)
    for description, situation in situations.items():
        assert analyzer.analyze(situation, None) is not None, description


@pytest.mark.parametrize("name", ANALYZER_NAMES)
def test_an_analyser_reports_a_threat_level_in_range(name, situations):
    analyzer = ANALYZERS.build(name)
    for description, situation in situations.items():
        threat = analyzer.analyze(situation, settled()).base_threat
        assert threat in (0, 1, 2, 3), f"{description}: {threat}"


@pytest.mark.parametrize("name", ANALYZER_NAMES)
def test_an_analyser_only_reports_crowding_for_uavs_that_are_flying(name, situations):
    analyzer = ANALYZERS.build(name)
    for description, situation in situations.items():
        flying = {report.uav_id for report in situation.alive()}
        assert set(analyzer.analyze(situation, settled()).crowding) <= flying, description


# --- planners ---------------------------------------------------------------


@pytest.mark.parametrize("name", PLANNER_NAMES)
def test_a_planner_answers_with_an_allocation(name, situations):
    planner = PLANNERS.build(name)
    for description, situation in situations.items():
        allocation = planner.plan(situation, symptoms_for(situation), settled())
        assert isinstance(allocation, Allocation), description


@pytest.mark.parametrize("name", PLANNER_NAMES)
def test_a_planner_only_ever_names_policies_that_exist(name, situations, sim_config):
    """A directive naming a policy the simulation does not have is dropped by the effector and wasted."""
    sim_config(DEFAULT_UAV_POLICY="firefighter")
    planner = PLANNERS.build(name)
    for description, situation in situations.items():
        for directive in planner.plan(situation, symptoms_for(situation), settled()).directives:
            assert directive.policy in POLICIES, f"{description}: {directive.policy!r}"


@pytest.mark.parametrize("name", PLANNER_NAMES)
def test_a_planner_never_gives_orders_to_a_uav_that_is_not_flying(name, situations):
    planner = PLANNERS.build(name)
    for description, situation in situations.items():
        flying = {report.uav_id for report in situation.alive()}
        for directive in planner.plan(situation, symptoms_for(situation), settled()).directives:
            assert directive.uav_id in flying, description


@pytest.mark.parametrize("name", PLANNER_NAMES)
def test_a_planner_gives_each_uav_at_most_one_order(name, situations):
    """Two directives for one UAV would make what it ends up flying a matter of iteration order."""
    planner = PLANNERS.build(name)
    for description, situation in situations.items():
        ordered = [d.uav_id for d in planner.plan(situation, symptoms_for(situation),
                                                  settled()).directives]
        assert len(ordered) == len(set(ordered)), description


@pytest.mark.parametrize("name", PLANNER_NAMES)
def test_a_planner_works_without_a_knowledge_base(name, situations):
    """Hysteresis is the Knowledge base's; a planner handed None applies its decisions directly."""
    planner = PLANNERS.build(name)
    for description, situation in situations.items():
        assert planner.plan(situation, symptoms_for(situation), None) is not None, description


@pytest.mark.parametrize("name", PLANNER_NAMES)
def test_a_planner_says_why(name, situations):
    """The rationale is logged and shown on the status panel; a silent planner cannot be checked."""
    planner = PLANNERS.build(name)
    situation = situations["the base alight"]
    assert planner.plan(situation, symptoms_for(situation), settled()).rationale.strip()


@pytest.mark.parametrize("name", PLANNER_NAMES)
def test_a_planner_produces_a_directive_that_survives_the_wire(name, situations):
    """Any allocation may be answered by a server, so all of them have to round trip through JSON."""
    planner = PLANNERS.build(name)
    situation = situations["the base alight"]
    allocation = planner.plan(situation, symptoms_for(situation), settled())
    assert Allocation.from_json(allocation.to_json()) == allocation


@pytest.mark.parametrize("name", PLANNER_NAMES)
def test_these_tests_actually_saw_some_directives(name, situations):
    """A guard on the tests above rather than on the planner.

    Every assertion up there is of the form "each directive is sound", which passes trivially over an
    allocation with no directives in it -- and that is not a hypothetical: run these through the default
    hysteresis and *no* planner issues anything on a first evaluation, so the whole file would go green
    without checking a thing. This fails if that ever becomes true again.
    """
    planner = PLANNERS.build(name)
    issued = sum(len(planner.plan(situation, symptoms_for(situation), settled()).directives)
                 for situation in situations.values())
    assert issued, f"the {name} planner issued nothing at all: the checks above tested nothing"


# --- the parameters they set ------------------------------------------------


@pytest.mark.parametrize("name", PLANNER_NAMES)
def test_a_planner_only_sets_parameters_the_policies_understand(name, situations):
    """Anything else is refused by the effector, so setting it is a decision that never takes effect."""
    from sim.policy import PolicyParams

    allowed = set(PolicyParams().to_json())
    planner = PLANNERS.build(name)
    for description, situation in situations.items():
        for directive in planner.plan(situation, symptoms_for(situation), settled()).directives:
            assert set(directive.params) <= allowed, f"{description}: {directive.params}"


@pytest.mark.parametrize("name", PLANNER_NAMES)
def test_a_planner_keeps_the_speed_cap_within_bounds(name, situations):
    planner = PLANNERS.build(name)
    for description, situation in situations.items():
        for directive in planner.plan(situation, symptoms_for(situation), settled()).directives:
            cap = directive.params.get("speed_cap")
            assert cap is None or 0 <= cap <= config.UAV_SPEED, f"{description}: {cap}"
