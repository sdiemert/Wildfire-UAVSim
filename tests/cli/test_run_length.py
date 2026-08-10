"""Tests for how headless.py decides how long a run lasts.

These exist because of a wrong answer, not a crash. `--steps` used to set how many times the runner called
step(), independently of BATCH_SIZE, which the model itself stops on. Both directions were silently wrong:
above BATCH_SIZE the flag did nothing, and below it the loop stopped before the model had finished -- and a
run stopped early has not lost its home base yet, so it was scored WON. A sweep over 120, 150 and 200 steps
came back with three identical win rates, which read convincingly as the run length not mattering. It is the
opposite of the truth: run length is the strongest difficulty dial in the configuration, and the mistake only
surfaced when a tuned config.py produced 3.5% where the sweeps had predicted 10.9%.

So --steps is now an alias for BATCH_SIZE, and the tests below are about the two of them being one number.
The end-to-end ones run main() for real on a grid small enough to be a unit test, because the trap lived in
the gap between what the runner counted and what the model did, and only a real run closes that gap.
"""

# python libraries

import importlib
import json

import pytest

# own python modules

import config
from sim.cli.main import main

# sim/cli/__init__.py re-exports main(), so the name 'main' on the package is the function and not the
# module of the same name. import_module goes by the dotted name, which is the module the fixture below
# needs to patch run_batch on.
cli = importlib.import_module("sim.cli.main")

# no home base, so the step budget is the only thing that can end these runs: losing the base stops a run
# too, and a run that ended for the other reason would say nothing about the run length
NO_BASE = ["--runs", "1", "--log-level", "ERROR",
           "--set", "WIDTH=12", "--set", "HEIGHT=12", "--set", "NUM_AGENTS=2",
           "--set", "DENSITY_PROB=1.0", "--set", "FIRE_START_STEP=0",
           "--set", "ACTIVATE_FIREFIGHTING=False"]


@pytest.fixture(autouse=True)
def restore_config():
    """Puts config.py back after each test.

    main() applies the overrides in this process as well as in the workers, as its fail-fast check that
    the configuration is valid before a batch starts. So a run leaks its settings into whatever runs
    next -- BATCH_SIZE included, which is the one thing these tests read.
    """
    saved = {name: getattr(config, name) for name in dir(config) if name.isupper()}
    yield
    for name, value in saved.items():
        setattr(config, name, value)


@pytest.fixture
def run(tmp_path):
    """Runs a batch and returns its results, as the JSON a reader of an experiment would get."""

    def _run(*options, expect=0):
        output = tmp_path / "results.json"
        code = main([*NO_BASE, "--output", str(output), *options])
        assert code == expect, f"headless.py exited {code}"
        return json.loads(output.read_text()) if output.exists() else None

    return _run


@pytest.fixture
def configs(monkeypatch):
    """Captures the RunConfigs a batch would have been executed with, without executing it."""
    captured = []

    def fake_run_batch(configs, workers, executor, log_level, log):
        captured.extend(configs)
        return []

    monkeypatch.setattr(cli, "run_batch", fake_run_batch)
    return captured


# --- --steps is BATCH_SIZE --------------------------------------------------


def test_steps_above_the_configured_batch_size_lengthens_the_run(run):
    """The regression itself: this used to stop at BATCH_SIZE and report a shorter run.

    130 is above the configured 100 deliberately. Under the old behaviour the model cleared 'running' at
    its own 100 and the extra 30 were never simulated, which is what made a sweep of 120, 150 and 200
    return one number three times.
    """
    longer = config.BATCH_SIZE + 30

    result = run("--steps", str(longer))[0]

    assert result["steps_completed"] == longer


def test_steps_below_the_configured_batch_size_shortens_the_run(run):
    result = run("--steps", "12")[0]

    assert result["steps_completed"] == 12


def test_without_steps_a_run_lasts_the_configured_batch_size(run):
    """The default path, which is what every published number was produced on."""
    result = run()[0]

    assert result["steps_completed"] == config.BATCH_SIZE


def test_set_batch_size_still_sets_the_run_length_on_its_own(run):
    """The spelling the sweep tool uses, and the one --steps used to be a broken shortcut for."""
    result = run("--set", "BATCH_SIZE=17")[0]

    assert result["steps_completed"] == 17


def test_steps_reaches_the_worker_as_batch_size(configs):
    """A worker applies the overrides in its own process; a run length that stayed here would be silent.

    This is the mechanism the end-to-end tests above measure the effect of: --steps has to arrive as the
    constant the model reads, not only as the runner's loop bound.
    """
    assert main([*NO_BASE, "--steps", "130"]) == 0

    assert configs[0].overrides["BATCH_SIZE"] == 130
    assert configs[0].steps == 130


def test_the_loop_bound_and_the_constant_never_disagree(configs):
    """Whichever way the run length was spelled, the two numbers are one number."""
    assert main([*NO_BASE, "--set", "BATCH_SIZE=42"]) == 0

    assert configs[0].steps == configs[0].overrides["BATCH_SIZE"] == 42


# --- saying it twice --------------------------------------------------------


def test_steps_and_set_batch_size_may_not_disagree(run):
    """Two names for one setting, so a contradiction is a mistake and not a precedence question.

    Silently letting one win is how the original trap read to whoever hit it: the run length that came out
    was not the one that went in, and nothing said so.
    """
    run("--steps", "150", "--set", "BATCH_SIZE=100", expect=2)


def test_steps_and_set_batch_size_may_agree(run):
    """Saying the same thing twice is redundant, not wrong."""
    result = run("--steps", "12", "--set", "BATCH_SIZE=12")[0]

    assert result["steps_completed"] == 12
