"""Tests for the name -> class lookup the five MAPE-K roles share.

There is one Registry per role, and everything that selects a component goes through it: a managing system
naming one in systems.py, `--mape planner=static`, and the defaults a system does not state. So the two
things that matter here are that a name which does not exist says what does, and that a name which does
exist cannot quietly mean two different classes.
"""

# python libraries

import pytest

# own python modules

from sim.managing import ANALYZERS, EXECUTORS, KNOWLEDGE_BASES, MONITORS, PLANNERS, REGISTRIES
from sim.managing.plan import HeuristicPlanner, StaticPlanner
from sim.managing.registry import Registry

ROLE_REGISTRIES = [MONITORS, ANALYZERS, PLANNERS, EXECUTORS, KNOWLEDGE_BASES]


# --- looking a component up -------------------------------------------------


def test_a_registered_component_is_found():
    assert PLANNERS.lookup("static") is StaticPlanner


def test_an_unknown_name_says_what_there_is():
    with pytest.raises(KeyError) as raised:
        PLANNERS.lookup("no-such-planner")
    message = str(raised.value)
    assert "no-such-planner" in message
    for name in PLANNERS.names():
        assert name in message, "the error has to list what could have been meant"


def test_the_role_is_named_in_the_error():
    """So that 'unknown analyzer' cannot be mistaken for a mistyped planner."""
    with pytest.raises(KeyError, match="analyzer"):
        ANALYZERS.lookup("static")     # a real planner, but not an analyser


# --- building ---------------------------------------------------------------


def test_building_by_name_gives_an_instance():
    assert isinstance(PLANNERS.build("heuristic"), HeuristicPlanner)


def test_building_nothing_gives_the_default():
    assert isinstance(PLANNERS.build(), HeuristicPlanner)
    assert PLANNERS.default == "heuristic"


def test_something_already_built_is_passed_through():
    """A test or a hand-composed managing system holds an instance; it uses the same argument."""
    planner = StaticPlanner()
    assert PLANNERS.build(planner) is planner


def test_constructor_arguments_reach_the_component():
    assert PLANNERS.build("static", policy="random").policy == "random"


# --- registering ------------------------------------------------------------


def test_two_components_cannot_share_a_name():
    """Which of them a managing system got would otherwise depend on import order."""

    class Duplicate(StaticPlanner):
        name = "static"

    with pytest.raises(ValueError, match="static"):
        Registry("planner", (StaticPlanner, Duplicate))


def test_a_component_without_a_name_cannot_be_registered():
    class Nameless(StaticPlanner):
        name = None

    with pytest.raises(ValueError, match="Nameless"):
        Registry("planner", (Nameless,))


def test_registering_the_same_class_twice_is_harmless():
    registry = Registry("planner", (StaticPlanner,))
    registry.add(StaticPlanner)
    assert registry.names() == ["static"]


# --- the roles themselves ---------------------------------------------------


@pytest.mark.parametrize("registry", ROLE_REGISTRIES, ids=lambda registry: registry.role)
def test_every_role_has_at_least_one_component_and_a_default(registry):
    assert registry.names(), f"nothing is registered as a {registry.role}"
    assert registry.default in registry


def test_the_five_roles_are_the_ones_a_managing_system_is_composed_from():
    """REGISTRIES is what everything else iterates over, so it has to be the whole of MAPE-K."""
    assert set(REGISTRIES) == {"monitor", "analyzer", "planner", "executor", "knowledge"}
