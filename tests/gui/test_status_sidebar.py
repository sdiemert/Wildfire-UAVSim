"""Tests that the status panel renders for every kind of model it can be shown.

These exist because the panel read `model.managing.planner.name`, which a local managing system has and a
remote one does not, so selecting 'remote' in the web interface raised AttributeError inside Mesa's render
loop and killed the websocket -- the simulation simply stopped, with a traceback in the console.

It survived an earlier check that rendered the panel for 'none' and 'local' and never tried 'remote'. So
the parametrisation over all three is the point of this file, and anything added to the panel should be
covered for all of them rather than for whichever one was in mind at the time.
"""

# python libraries

import random

import pytest

# own python modules

from sim.gui.canvas_grid import CanvasGrid
from sim.gui.portrayal import agent_portrayal
from sim.gui.status_sidebar import StatusSidebar
from sim.gui.top_bar import TopBar
from sim.managing import MANAGING_SYSTEMS

# every managing system that can be picked from the dropdown, read from the registry rather than listed,
# so that one added to sim/managing/systems.py is rendered here before anybody sees it in a browser
MANAGING_KINDS = sorted(MANAGING_SYSTEMS)


@pytest.fixture
def model(sim_config):
    """An AdaptiveWildFireModel of any kind, on a small grid."""

    def _make(managing, steps=0, **overrides):
        settings = {"WIDTH": 15, "HEIGHT": 15, "NUM_AGENTS": 3, "BATCH_SIZE": 10_000,
                    "DENSITY_PROB": 1.0, "FIRE_START_POSITION": None, "FIRE_START_STEP": 0,
                    "ACTIVATE_FIREFIGHTING": True, "MANAGING_SYSTEM": "local",
                    # nothing is listening, so a remote run exercises the fallback path as well
                    "MANAGING_SYSTEM_URL": "http://127.0.0.1:1/manage",
                    "MANAGING_SYSTEM_TIMEOUT": 0.05}
        settings.update(overrides)
        sim_config(**settings)

        from sim.adaptive import AdaptiveWildFireModel

        built = AdaptiveWildFireModel(managing=managing, policy="firefighter")
        for _ in range(steps):
            built.step()
        return built

    return _make


# --- the regression ---------------------------------------------------------


@pytest.mark.parametrize("managing", MANAGING_KINDS)
def test_the_panel_renders_before_the_run_starts(model, managing):
    assert isinstance(StatusSidebar().render(model(managing)), str)


@pytest.mark.parametrize("managing", MANAGING_KINDS)
def test_the_panel_renders_once_the_run_is_going(model, managing):
    """The one that was missing: 'remote' raised AttributeError here and killed the websocket."""
    assert isinstance(StatusSidebar().render(model(managing, steps=5)), str)


@pytest.mark.parametrize("managing", MANAGING_KINDS)
def test_every_element_on_the_page_renders(model, managing):
    built = model(managing, steps=3)
    for element in (StatusSidebar(), TopBar(), CanvasGrid(agent_portrayal, 15, 15, 150, 150)):
        assert element.render(built) is not None, type(element).__name__


@pytest.mark.parametrize("managing", MANAGING_KINDS)
def test_the_panel_renders_after_a_uav_is_destroyed(model, managing):
    import config

    built = model(managing, steps=2)
    doomed = built.uavs[0]
    doomed.take_damage(config.UAV_HP)
    built.destroy_uav(doomed)
    built.step()
    assert isinstance(StatusSidebar().render(built), str)


# --- what it says -----------------------------------------------------------


def test_an_unmanaged_run_gets_no_managing_section(model):
    assert "Managing system" not in StatusSidebar().render(model("none", steps=3))


@pytest.mark.parametrize("managing", [name for name in MANAGING_KINDS if name != "none"])
def test_a_managed_run_says_which_managing_system_is_running_and_where(model, managing):
    panel = StatusSidebar().render(model(managing, steps=3))
    assert "Managing system" in panel
    assert managing in panel, "the panel has to name the managing system that was selected"
    assert ("remote" if managing == "remote" else "local") in panel


@pytest.mark.parametrize("managing", [name for name in MANAGING_KINDS
                                      if name not in ("none", "remote")])
def test_a_locally_managed_run_says_which_of_its_parts_are_not_the_usual_ones(model, managing):
    """A managing system is a combination of interchangeable parts, and its name does not say which.

    Only the parts that differ from the default for their role are shown. Naming all five spent three of
    this section's six lines saying 'default' three times, which is what made the panel unreadable; what
    is left is the part a reader could not have guessed from the name.
    """
    from sim.managing import REGISTRIES

    built = model(managing, steps=3)
    panel = StatusSidebar().render(built)
    for role, name in built.composition().items():
        if name != REGISTRIES[role].default:
            assert name in panel, f"the panel does not say it is running the {name} {role}"


def test_a_managing_system_made_of_nothing_unusual_says_nothing_about_it(model):
    """'heuristic' is every default there is, so its name has already said all of this."""
    panel = StatusSidebar().render(model("heuristic", steps=3))
    assert "Made of" not in panel


def test_the_parts_that_are_worth_showing_are_shown(model):
    panel = StatusSidebar().render(model("defensive", steps=3))
    assert "Made of" in panel
    assert "cautious" in panel and "defensive" in panel
    assert "default" not in panel, "the defaults are noise: three of five said 'default'"


def test_a_remotely_managed_run_does_not_claim_components_it_cannot_know(model):
    """They are the server's. Showing the local defaults would be a guess presented as a fact."""
    assert model("remote", steps=3).composition() == {}


def test_a_remote_run_that_fell_back_says_so(model):
    # the URL in the fixture points at nothing, so every evaluation falls back to the local stand-in
    panel = StatusSidebar().render(model("remote", steps=4))
    assert "Fell back" in panel, "a run that lost its server must not look like a healthy remote run"


def test_a_managed_run_reports_what_each_uav_is_flying(model):
    built = model("local", steps=4)
    panel = StatusSidebar().render(built)
    for name in set(built.allocation().values()):
        assert name in panel


# --- the allocation, as a bar of the whole team -----------------------------


def test_the_allocation_is_drawn_as_one_bar_however_many_policies_are_flying(model):
    """A list of counts grew a line for every two policies; the bar is one line whatever happens."""
    built = model("heuristic", steps=6)
    panel = StatusSidebar().render(built)
    assert panel.count('<div class="bar">') == 1


def test_the_bar_accounts_for_the_whole_team(model):
    import re

    built = model("heuristic", steps=6)
    panel = StatusSidebar().render(built)
    widths = [float(w) for w in re.findall(r'width:([\d.]+)%', panel)]
    assert widths, "no segments were drawn"
    assert abs(sum(widths) - 100.0) < 0.5, f"the segments cover {sum(widths)}% of the bar"


def test_the_bar_is_drawn_in_the_colours_the_uavs_are_drawn_in(model):
    """The panel is the map's key, so the two have to agree or it is worse than no key at all."""
    import config

    from sim.gui.portrayal import uav_color

    built = model("heuristic", steps=6)
    panel = StatusSidebar().render(built)
    for uav in built.active_uavs():
        colour = uav_color(uav)
        if colour != config.UAV_COLOR or built.allocation().get(uav.unique_id) in config.POLICY_COLORS:
            assert colour in panel, f"{colour} is on the map but not in the legend"


def test_the_legend_names_each_policy_and_counts_it(model):
    built = model("heuristic", steps=6)
    panel = StatusSidebar().render(built)
    counts = {}
    flying = {uav.unique_id for uav in built.active_uavs()}
    for uav_id, name in built.allocation().items():
        if uav_id in flying:
            counts[name] = counts.get(name, 0) + 1
    for name, count in counts.items():
        assert f'>{name}</span><span class="value">{count}</span>' in panel


# --- the rationale ----------------------------------------------------------


def test_the_rationale_is_repeated_in_a_tooltip(model):
    """It is clamped to two lines, so the whole of it has to be reachable somewhere."""
    built = model("heuristic", steps=6)
    panel = StatusSidebar().render(built)
    rationale = built.rationale()
    assert rationale, "this test needs a run that produced one"
    assert f'title="{rationale}"' in panel


def test_a_rationale_from_a_server_cannot_inject_markup(model):
    """The one string on the page a remote managing system supplies, written straight into innerHTML.

    Everything else that arrives from a server is validated against the simulation before it is shown -- a
    policy name has to be one the simulation has -- but free text cannot be, so it has to be escaped.
    """
    built = model("heuristic", steps=3)
    built.managing.knowledge.rationale = '<img src=x onerror="alert(1)">"pwned"'
    panel = StatusSidebar().render(built)
    assert "<img" not in panel
    assert "onerror" not in panel or "&quot;" in panel
    assert "&lt;img" in panel


# --- the cramping this was all about ----------------------------------------


def test_a_long_value_is_cut_rather_than_spilling_into_the_cell_beside_it(model):
    """.name was always cut this way and .value was not, so the wider half was the one that overflowed."""
    panel = StatusSidebar().render(model("defensive", steps=3))
    styles = panel[panel.find("<style>"):panel.find("</style>")]
    value_rule = styles[styles.find("#status-sidebar .value"):]
    assert "text-overflow: ellipsis" in value_rule[:value_rule.find("}")]


def test_the_name_of_the_managing_system_gets_a_line_to_itself(model):
    """It is a name, not a number: half a line is about twenty characters and it does not fit."""
    panel = StatusSidebar().render(model("defensive", steps=3))
    assert '<div class="grid wide">' in panel


def test_the_managing_section_is_at_most_a_handful_of_lines(model):
    """The whole point of this layout. Six lines of it was what pushed the team off the column."""
    built = model("defensive", steps=6)
    panel = StatusSidebar().render(built)
    section = panel[panel.find("Managing system"):panel.find("<h4>UAVs")]
    rows = section.count('<div class="cell">') + section.count('<div class="bar">') \
        + section.count('<div class="quote"')
    assert rows <= 5, f"the managing section is back up to {rows} rows"


def test_a_run_managed_on_a_server_does_not_say_remote_twice(model):
    panel = StatusSidebar().render(model("remote", steps=3))
    assert "remote &middot; remote" not in panel


def test_the_policy_a_uav_is_flying_is_not_the_first_thing_truncated(model):
    """It lives in a span of its own: .who is the one that gives way when the column is narrow."""
    built = model("heuristic", steps=6)
    panel = StatusSidebar().render(built)
    for name in set(built.allocation().values()):
        assert f'class="tag"' in panel
        assert f'>{name}</span>' in panel


# --- the positioning error extension ----------------------------------------


def test_a_uav_line_carries_both_where_it_is_and_where_it_thinks_it_is(model):
    """The pair is the point: the gap between them is the whole of what the extension does."""
    built = model("none", steps=3, ACTIVATE_POSITION_ERROR=True,
                  UAV_POSITION_BIAS_MAX=3, UAV_POSITION_NOISE_MAX=0)
    # a bias large enough that no UAV can be reporting its own cell by chance
    for uav in built.uavs:
        uav.position_bias = (3, 3)
        uav._position_offset = (None, (0, 0))

    panel = StatusSidebar().render(built)
    for uav in built.uavs:
        assert f"{uav.pos}</span>" in panel, "where the UAV really is"
        assert f"~{uav.measured_pos()}</span>" in panel, "where it believes it is"


def test_a_uav_that_knows_where_it_is_is_not_made_to_look_interesting(model):
    """An exact fix is greyed and a wrong one is not, so the column can be scanned for the wrong ones."""
    built = model("none", steps=3, ACTIVATE_POSITION_ERROR=True,
                  UAV_POSITION_BIAS_MAX=0, UAV_POSITION_NOISE_MAX=0)
    assert 'class="fix muted"' in StatusSidebar().render(built)

    for uav in built.uavs:
        uav.position_bias = (2, -2)
        uav._position_offset = (None, (0, 0))
    assert 'class="fix warn"' in StatusSidebar().render(built)


def test_no_second_position_is_shown_when_the_extension_is_off(model):
    built = model("none", steps=3, ACTIVATE_POSITION_ERROR=False)
    panel = StatusSidebar().render(built)

    assert 'class="fix' not in panel
    assert "is ~ thinks" not in panel


def test_watching_a_run_in_the_browser_does_not_change_it(model):
    """The invariant the panel's UAV loop rests on, kept here rather than in a comment.

    A UAV draws the jitter in its fix the first time it is asked for on a step, so the panel takes real
    draws from SYSTEM_RANDOM while it renders. Asking every UAV still flying, in team order, takes exactly
    the draws the next step was going to take anyway and in the same order, so a run watched in the browser
    is the same run as one nobody is looking at. A partial pass, or a pass in some other order, would hand
    one UAV the numbers another was about to get, and the two runs below would part company.
    """
    def outcome(watched):
        built = model("none", SYSTEM_RANDOM=random.Random(9), ACTIVATE_POSITION_ERROR=True,
                      UAV_POSITION_BIAS_MAX=2, UAV_POSITION_NOISE_MAX=1)
        panel = StatusSidebar()
        for _ in range(12):
            built.step()
            if watched:
                panel.render(built)
        return ([uav.pos for uav in built.uavs],
                [round(uav.fuel, 6) for uav in built.uavs],
                [fire.burning for fire in built.fire_list],
                built.MR2_VALUE, built.collisions)

    assert outcome(watched=True) == outcome(watched=False)


def test_the_map_shows_true_positions_only(model):
    """The canvas is drawn cell by cell rather than UAV by UAV, so it must not ask for a fix at all.

    A pass in grid order would take the draws out of team order, which is exactly what the panel is careful
    not to do; the map has the true positions to hand anyway, since it is walking the grid to find them.
    """
    built = model("none", steps=2, ACTIVATE_POSITION_ERROR=True, UAV_POSITION_BIAS_MAX=3,
                  UAV_POSITION_NOISE_MAX=0)
    for uav in built.uavs:
        uav.position_bias = (3, 3)
        uav._position_offset = (None, (0, 0))

    drawn = CanvasGrid(agent_portrayal, 15, 15, 150, 150).render(built)
    marks = {(item["x"], item["y"]) for layer in drawn.values() for item in layer}
    for uav in built.uavs:
        assert uav.pos in marks
