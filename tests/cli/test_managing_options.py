"""Tests for the command line options that select a managing system.

These run headless.py's main() for real, on a grid small enough to finish in a moment. That is deliberate:
the last time a field was renamed, the only thing reading it was a reporting path nothing executed, and the
break surfaced as a crash after a batch had finished rather than as a failing test. Every option here is on
a path that only runs when somebody runs a batch, so the way to cover them is to run one.
"""

# python libraries

import json

import pytest

# own python modules

from sim.cli.main import main
from sim.managing import MANAGING_SYSTEMS

# a run small enough to be a unit test and long enough for the managing system to evaluate several times
SMALL = ["--runs", "1", "--steps", "3", "--log-level", "ERROR",
         "--set", "WIDTH=12", "--set", "HEIGHT=12", "--set", "NUM_AGENTS=3",
         "--set", "DENSITY_PROB=1.0", "--set", "FIRE_START_STEP=0"]


@pytest.fixture
def run(tmp_path):
    """Runs a batch and returns its results, as the JSON a reader of an experiment would get."""

    def _run(*options, expect=0):
        output = tmp_path / "results.json"
        code = main([*SMALL, "--output", str(output), *options])
        assert code == expect, f"headless.py exited {code}"
        return json.loads(output.read_text()) if output.exists() else None

    return _run


# --- listing what there is --------------------------------------------------


def test_the_managing_systems_can_be_listed(capsys):
    assert main(["--list-managing"]) == 0
    printed = capsys.readouterr().out
    for name in MANAGING_SYSTEMS:
        assert name in printed


def test_listing_them_does_not_run_anything(capsys):
    """It is a question about the code, so it must not need a valid configuration or a simulation."""
    assert main(["--list-managing", "--set", "WIDTH=0"]) == 0


# --- selecting one ----------------------------------------------------------


@pytest.mark.parametrize("name", sorted(MANAGING_SYSTEMS))
def test_every_managing_system_can_be_run_from_the_command_line(run, name):
    if name == "remote":
        pytest.skip("covered by test_remote.py; there is no server here")
    results = run("--managing", name)
    assert results[0]["managing_system"] == name


def test_an_unmanaged_run_says_so(run):
    result = run("--managing", "none")[0]
    assert result["managing"] is False
    assert result["managing_components"] == {}


def test_a_managed_run_records_what_managed_it(run):
    """Which arm produced a results file has to be readable off the file itself."""
    result = run("--managing", "defensive")[0]
    assert result["managing_system"] == "defensive"
    assert result["managing_location"] == "local"
    assert result["managing_components"]["planner"] == "defensive"
    assert result["managing_components"]["analyzer"] == "cautious"


def test_an_alias_is_recorded_under_the_name_that_ran(run):
    assert run("--managing", "local")[0]["managing_system"] == "heuristic"


def test_an_unknown_managing_system_stops_the_batch(run):
    """Before it starts, rather than as N identical failed runs."""
    run("--managing", "telepathy", expect=2)


# --- overriding a component -------------------------------------------------


def test_a_component_can_be_swapped_from_the_command_line(run):
    result = run("--managing", "heuristic", "--mape", "planner=static")[0]
    assert result["managing_system"] == "heuristic"
    assert result["managing_components"]["planner"] == "static"


def test_several_components_can_be_swapped_at_once(run):
    result = run("--managing", "heuristic",
                 "--mape", "planner=defensive", "--mape", "analyzer=cautious")[0]
    assert result["managing_components"]["planner"] == "defensive"
    assert result["managing_components"]["analyzer"] == "cautious"


def test_swapping_a_component_reaches_the_worker(run):
    """RunConfig is pickled into another process, so an override that stayed here would be silent."""
    swapped = run("--managing", "heuristic", "--mape", "planner=static", "--workers", "1")[0]
    assert swapped["managing_components"]["planner"] == "static"


def test_an_unknown_component_stops_the_batch(run):
    run("--managing", "heuristic", "--mape", "planner=telepathy", expect=2)


def test_an_unknown_role_stops_the_batch(run):
    run("--managing", "heuristic", "--mape", "plannner=static", expect=2)


# --- the arms of an experiment ----------------------------------------------


def test_the_control_arm_is_managed_but_never_adapts(run):
    """'static' is what separates what SuperPolicy is worth from what adapting is worth."""
    static = run("--managing", "static", "--seed", "3")[0]
    assert static["managing"] is True
    assert static["adaptations"] <= 1, "the control arm allocated more than once"


def test_the_same_seed_gives_the_same_run(run):
    """Comparing two arms only means anything if the fires are the same in both."""
    first = run("--managing", "heuristic", "--seed", "5")[0]
    again = run("--managing", "heuristic", "--seed", "5")[0]
    for field in ("mr1_total", "collisions", "adaptations", "burning_cells_final"):
        assert first[field] == again[field], field
