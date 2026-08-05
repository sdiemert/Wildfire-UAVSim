"""Tests for the registry of named managing systems.

The point of the registry is that adding a managing system is one entry in one tuple. That only holds if
nothing has to be added here to go with it, so most of what follows is parametrised over REGISTERED and
covers a new system the moment it is registered -- the same arrangement the policy tests use in
tests/policy/test_policy_interface.py.

What each managing system *does* is its own file's business (test_plan_static.py and the rest). What is
checked here is that every one of them can be built, that it is built out of what it says it is, and that
the ways of selecting one -- by name, by alias, by overriding a component -- behave.
"""

# python libraries

import pytest

# own python modules

import config

from sim.managing import ManagingSystem, RemoteManagingSystem
from sim.managing.systems import (ALIASES, MANAGING_SYSTEMS, REGISTERED, REGISTRIES, ROLES,
                                  ManagingSystemSpec, build_managing_system, managing_system)

LOCAL = [spec for spec in REGISTERED if spec.location == "local"]


class FakeSensor:
    def read(self):
        return None


class FakeEffector:
    def apply(self, allocation):
        return len(allocation.directives)


@pytest.fixture
def parts():
    return FakeSensor(), FakeEffector()


def build(name, parts, **kwargs):
    sensor, effector = parts
    return build_managing_system(sensor, effector, managing=name, **kwargs)


# --- every registered system, whatever it is --------------------------------


@pytest.mark.parametrize("spec", REGISTERED, ids=lambda spec: spec.name)
def test_every_registered_managing_system_builds(spec, parts):
    """Registering one is meant to be the whole of adding one; this is what says so."""
    system = build(spec.name, parts)
    if spec.location == "none":
        assert system is None
    else:
        assert system is not None
        assert system.name == spec.name
        assert system.location == spec.location


@pytest.mark.parametrize("spec", REGISTERED, ids=lambda spec: spec.name)
def test_every_registered_managing_system_names_components_that_exist(spec):
    for role in ROLES:
        REGISTRIES[role].lookup(getattr(spec, role))


@pytest.mark.parametrize("spec", REGISTERED, ids=lambda spec: spec.name)
def test_every_registered_managing_system_says_what_it_is_for(spec):
    """The description is what --list-managing and the web interface show; an empty one helps nobody."""
    assert spec.description.strip()


@pytest.mark.parametrize("spec", REGISTERED, ids=lambda spec: spec.name)
def test_every_registered_managing_system_has_a_sane_location(spec):
    assert spec.location in ("none", "local", "remote")


def test_the_names_are_unique():
    assert len(MANAGING_SYSTEMS) == len(REGISTERED)


def test_there_is_an_unmanaged_baseline():
    """Every A/B the managing system is measured by needs one, so it cannot be removed by accident."""
    assert managing_system("none").location == "none"


# --- what a local system is actually built out of ---------------------------


@pytest.mark.parametrize("spec", LOCAL, ids=lambda spec: spec.name)
def test_a_local_system_is_built_from_the_components_it_names(spec, parts):
    system = build(spec.name, parts)
    assert system.composition() == spec.components()


@pytest.mark.parametrize("spec", LOCAL, ids=lambda spec: spec.name)
def test_a_local_system_is_tuned_the_way_it_says(spec, parts):
    system = build(spec.name, parts)
    assert system.period == (config.ADAPTATION_PERIOD if spec.period is None else spec.period)
    assert system.knowledge.hysteresis == (config.ADAPTATION_HYSTERESIS if spec.hysteresis is None
                                           else spec.hysteresis)


def test_a_system_that_states_no_tuning_follows_the_configuration(parts, sim_config):
    sim_config(ADAPTATION_PERIOD=4, ADAPTATION_HYSTERESIS=3)
    system = build("heuristic", parts)
    assert (system.period, system.knowledge.hysteresis) == (4, 3)


def test_a_system_that_states_its_own_tuning_keeps_it(parts, sim_config):
    """'reactive' is reactive whatever config.py says, or it is not a managing system in its own right."""
    sim_config(ADAPTATION_PERIOD=4, ADAPTATION_HYSTERESIS=3)
    system = build("reactive", parts)
    assert (system.period, system.knowledge.hysteresis) == (1, 1)


# --- selecting one ----------------------------------------------------------


def test_an_unknown_name_says_what_there_is(parts):
    with pytest.raises(KeyError) as raised:
        build("telepathy", parts)
    for name in MANAGING_SYSTEMS:
        assert name in str(raised.value)


@pytest.mark.parametrize("alias, resolved", sorted(ALIASES.items()))
def test_an_alias_resolves_to_what_it_stands_for(alias, resolved, parts):
    assert build(alias, parts).name == resolved


def test_nothing_selected_follows_the_configuration(parts, sim_config):
    sim_config(MANAGING_SYSTEM="static")
    assert build(None, parts).composition()["planner"] == "static"


def test_a_remote_system_is_given_the_url_it_was_handed(parts):
    assert build("remote", parts, url="http://server/manage").url == "http://server/manage"


def test_a_remote_system_stands_in_with_the_local_one_it_names(parts, sim_config):
    sim_config(MANAGING_SYSTEM_FALLBACK=True)
    system = build("remote", parts)
    assert isinstance(system, RemoteManagingSystem)
    stand_in = system.fallback_factory()
    assert isinstance(stand_in, ManagingSystem)
    assert stand_in.name == managing_system("remote").fallback


# --- overriding one component -----------------------------------------------


def test_a_component_can_be_swapped_without_registering_a_system(parts):
    system = build("heuristic", parts, components={"planner": "static"})
    assert system.composition()["planner"] == "static"
    # and nothing else moved with it
    assert system.composition()["analyzer"] == "heuristic"


def test_several_components_can_be_swapped_at_once(parts):
    system = build("heuristic", parts, components={"planner": "defensive", "analyzer": "cautious"})
    assert system.composition() == managing_system("defensive").components()


def test_an_override_beats_what_the_system_registered(parts):
    assert build("defensive", parts, components={"planner": "heuristic"}) \
        .composition()["planner"] == "heuristic"


def test_overriding_nothing_leaves_the_system_alone(parts):
    assert build("defensive", parts, components={}).composition() \
        == managing_system("defensive").components()


def test_an_unknown_role_is_refused():
    with pytest.raises(KeyError, match="planner"):     # the error lists the roles there are
        managing_system("heuristic").with_components({"plannner": "static"})


def test_an_unknown_component_is_refused():
    with pytest.raises(KeyError, match="unknown planner"):
        managing_system("heuristic").with_components({"planner": "no-such-planner"})


def test_overriding_does_not_change_the_registered_system():
    """A spec is frozen, so one run's overrides cannot leak into the next run in the same process."""
    before = managing_system("heuristic").components()
    managing_system("heuristic").with_components({"planner": "static"})
    assert managing_system("heuristic").components() == before


# --- the settings a system is built against ---------------------------------


def test_building_checks_the_managing_settings(parts, sim_config):
    """The web interface can select a managing system config.py does not name; the bounds still apply."""
    sim_config(MANAGING_SYSTEM="none", ADAPTATION_PERIOD=0)
    with pytest.raises(ValueError, match="ADAPTATION_PERIOD"):
        build("heuristic", parts)


def test_building_a_remote_system_checks_the_remote_settings(parts, sim_config):
    sim_config(MANAGING_SYSTEM_URL="not-a-url")
    with pytest.raises(ValueError, match="MANAGING_SYSTEM_URL"):
        build("remote", parts)


def test_building_a_local_system_ignores_the_remote_settings(parts, sim_config):
    sim_config(MANAGING_SYSTEM_URL="not-a-url", MANAGING_SYSTEM_TIMEOUT=-1)
    assert build("heuristic", parts) is not None


def test_nothing_is_built_or_checked_for_none(parts, sim_config):
    sim_config(ADAPTATION_PERIOD=0)
    assert build("none", parts) is None


# --- describing one ---------------------------------------------------------


@pytest.mark.parametrize("spec", REGISTERED, ids=lambda spec: spec.name)
def test_every_system_can_describe_itself(spec):
    """--list-managing prints this for each of them."""
    assert spec.name in spec.describe()


def test_a_local_system_describes_its_components():
    assert "P=defensive" in managing_system("defensive").describe()


def test_a_remote_system_does_not_claim_components_it_cannot_know():
    """They are the server's. Printing the local defaults would be a guess presented as a fact."""
    described = managing_system("remote").describe()
    assert "P=" not in described
    assert config.MANAGING_SYSTEM_URL in described


def test_a_spec_is_frozen():
    with pytest.raises(Exception):
        ManagingSystemSpec(name="x").name = "y"
