"""Tests for how agents are drawn, and in particular for colouring UAVs by the policy they are flying.

That colouring is the one change in this interface that alters what the *map* shows rather than what the
panel beside it says, and it reverses a decision the map was built on -- every UAV in the same near black,
because that is what keeps it findable over a deliberately light background. So what these check is that
the reversal is confined to what it was for: a UAV is still dark, still outlined, and still drawn in the
old colour whenever there is no policy allocation to show or the setting is turned off.

The panel's legend is drawn from the same palette. If the two ever disagree the key is worse than no key at
all, which is what tests/gui/test_status_sidebar.py checks from the other side.
"""

# python libraries

import pytest

# own python modules

import config

from sim.gui.portrayal import agent_portrayal, allocated_policy, uav_color
from sim.managing import MANAGING_SYSTEMS
from sim.policy import POLICIES


@pytest.fixture
def model(sim_config):
    """An AdaptiveWildFireModel on a small grid, run far enough to have allocated something."""

    def _make(managing="heuristic", steps=6, **overrides):
        settings = {"WIDTH": 15, "HEIGHT": 15, "NUM_AGENTS": 4, "BATCH_SIZE": 10_000,
                    "DENSITY_PROB": 1.0, "FIRE_START_POSITION": None, "FIRE_START_STEP": 0,
                    "ACTIVATE_FIREFIGHTING": True, "MANAGING_SYSTEM": "heuristic",
                    "COLOUR_UAVS_BY_POLICY": True}
        settings.update(overrides)
        sim_config(**settings)

        from sim.adaptive import AdaptiveWildFireModel

        built = AdaptiveWildFireModel(managing=managing, policy="firefighter")
        for _ in range(steps):
            built.step()
        return built

    return _make


# --- the palette ------------------------------------------------------------


def test_every_policy_the_managing_system_can_allocate_has_a_colour():
    """A policy without one is drawn as an ordinary UAV, which is fine -- but the two it allocates most
    are what the whole idea rests on, so those are worth insisting on."""
    for name in ("firefighter", "defend-base", "disperse"):
        assert name in config.POLICY_COLORS


def test_the_colours_are_distinct():
    used = list(config.POLICY_COLORS.values())
    assert len(set(used)) == len(used), "two policies share a colour, so the map cannot tell them apart"


def test_the_colours_are_dark_enough_to_find_on_a_light_map():
    """The reason every UAV used to be near black. A light one disappears into the vegetation."""
    for name, colour in config.POLICY_COLORS.items():
        red, green, blue = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
        luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
        assert luminance < 0.45, f"{name} is drawn in {colour}, which is too light to pick out"


def test_a_colour_is_named_for_a_policy_that_exists():
    for name in config.POLICY_COLORS:
        assert name in POLICIES, f"{name!r} has a colour but is not a registered policy"


# --- what a UAV is drawn in -------------------------------------------------


def test_a_uav_is_drawn_in_the_colour_of_the_policy_it_is_flying(model):
    built = model()
    for uav in built.active_uavs():
        allocated = built.allocation()[uav.unique_id]
        assert uav_color(uav) == config.POLICY_COLORS[allocated]


def test_a_uav_changes_colour_when_it_is_reallocated(model):
    """The whole point: the team turning colour is the managing system working, seen on the map."""
    built = model()
    uav = built.active_uavs()[0]
    before = uav_color(uav)
    built.policy.assign(uav.unique_id, "disperse" if before != config.POLICY_COLORS["disperse"]
                        else "firefighter")
    assert uav_color(uav) != before


def test_an_unmanaged_run_draws_every_uav_the_same(model):
    """No allocation to show, so the map is exactly what it always was."""
    built = model(managing="none")
    for uav in built.active_uavs():
        assert uav_color(uav) == config.UAV_COLOR


def test_a_plain_model_draws_every_uav_the_same(make_model):
    """The plain WildFireModel holds one policy for the team and has no allocated() to ask."""
    built = make_model(NUM_AGENTS=2)
    for uav in built.active_uavs():
        assert allocated_policy(uav) is None
        assert uav_color(uav) == config.UAV_COLOR


def test_the_colouring_can_be_turned_off(model):
    """The older, plainer map, where a UAV is a UAV and nothing else."""
    built = model(COLOUR_UAVS_BY_POLICY=False)
    for uav in built.active_uavs():
        assert uav_color(uav) == config.UAV_COLOR


def test_a_policy_with_no_colour_of_its_own_is_drawn_as_an_ordinary_uav(model):
    """So that adding a policy to the simulation costs nothing here until it is worth telling apart."""
    built = model()
    uav = built.active_uavs()[0]
    built.policy.assign(uav.unique_id, "follow-fire")
    saved = dict(config.POLICY_COLORS)
    try:
        config.POLICY_COLORS.pop("follow-fire", None)
        assert uav_color(uav) == config.UAV_COLOR
    finally:
        config.POLICY_COLORS.clear()
        config.POLICY_COLORS.update(saved)


# --- the rest of the portrayal is unchanged ---------------------------------


@pytest.mark.parametrize("managing", sorted(MANAGING_SYSTEMS))
def test_every_agent_can_be_drawn_under_every_managing_system(model, managing):
    """agent_portrayal runs once per agent per cell per frame; anything it raises kills the websocket."""
    if managing == "remote":
        pytest.skip("no server here; the fallback path is covered by the sidebar tests")
    built = model(managing=managing, steps=3)
    for agent in built.schedule.agents:
        portrayal = agent_portrayal(agent)
        assert portrayal is None or "Layer" in portrayal


def test_a_uav_keeps_its_outline_and_its_place_above_the_map(model):
    """The outline is what gives it an edge over the base and over burnt ground, whatever colour it is."""
    built = model()
    for uav in built.active_uavs():
        portrayal = agent_portrayal(uav)
        assert portrayal["stroke_color"] == config.UAV_OUTLINE_COLOR
        assert portrayal["Layer"] == 2


def test_water_is_still_shown_by_size_rather_than_by_colour(model):
    """Colour now says which policy, so the load has to go on saying what it always did."""
    built = model()
    uav = built.active_uavs()[0]
    uav.water = 1
    loaded = agent_portrayal(uav)
    uav.water = 0
    empty = agent_portrayal(uav)
    assert loaded["w"] > empty["w"]
    assert loaded["Color"] == empty["Color"]


def test_the_probability_map_is_unaffected(model, sim_config):
    """It draws nothing but the fire, and a UAV on it used to throw KeyError in the canvas."""
    built = model(NUM_AGENTS=0, steps=1)
    sim_config(PROBABILITY_MAP=True)
    for agent in built.schedule.agents:
        agent_portrayal(agent)
