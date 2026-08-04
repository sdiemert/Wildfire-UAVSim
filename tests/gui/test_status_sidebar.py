"""Tests that the status panel renders for every kind of model it can be shown.

These exist because the panel read `model.managing.planner.name`, which a local managing system has and a
remote one does not, so selecting 'remote' in the web interface raised AttributeError inside Mesa's render
loop and killed the websocket -- the simulation simply stopped, with a traceback in the console.

It survived an earlier check that rendered the panel for 'none' and 'local' and never tried 'remote'. So
the parametrisation over all three is the point of this file, and anything added to the panel should be
covered for all of them rather than for whichever one was in mind at the time.
"""

# python libraries

import pytest

# own python modules

from sim.gui.canvas_grid import CanvasGrid
from sim.gui.portrayal import agent_portrayal
from sim.gui.status_sidebar import StatusSidebar
from sim.gui.top_bar import TopBar

MANAGING_KINDS = ["none", "local", "remote"]


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


@pytest.mark.parametrize("managing", ["local", "remote"])
def test_a_managed_run_says_where_the_managing_system_is(model, managing):
    panel = StatusSidebar().render(model(managing, steps=3))
    assert "Managing system" in panel
    assert managing in panel


def test_a_remote_run_that_fell_back_says_so(model):
    # the URL in the fixture points at nothing, so every evaluation falls back to the local stand-in
    panel = StatusSidebar().render(model("remote", steps=4))
    assert "Fell back" in panel, "a run that lost its server must not look like a healthy remote run"


def test_a_managed_run_reports_what_each_uav_is_flying(model):
    built = model("local", steps=4)
    panel = StatusSidebar().render(built)
    for name in set(built.allocation().values()):
        assert name in panel
