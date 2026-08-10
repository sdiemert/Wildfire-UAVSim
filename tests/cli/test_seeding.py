"""Tests that parallel runs get independent random streams, and that every run records the seed it used.

Two defects motivate these. The first is that `--executor thread` corrupted a seeded batch. Seeding
replaces `config.SYSTEM_RANDOM`, which is a module attribute and so process-global, and threads share it:
with `--runs 6 --workers 4 --seed 1` a batch did not merely fail to reproduce, it produced *other runs'*
fires -- run 0 came back with the ignition belonging to seed 4. That was a log warning, which is not
enough, because the batch still finished and still wrote plausible JSON with a distinct seed recorded
against every run. It is now refused.

The second is that a batch run without `--seed` recorded `seed: None` and drew from SystemRandom, so the
run worth a second look could never be looked at twice. Every batch now runs on a real seed, drawn from
OS entropy when none was given and reported, which is what test_a_recorded_seed_replays_its_batch below
is really about.

These run main() for real, on a grid small enough to be a unit test, because the whole question is what
happens when several runs execute at once -- which nothing short of a real batch exercises.
"""

# python libraries

import json

import pytest

# own python modules

import config
from sim.cli.main import main

# Small, fast, and firefighting off so no run can end early by losing the base: these tests compare runs
# against each other, and a batch where some runs stopped at different steps for a second reason is
# harder to read than it needs to be.
SMALL = ["--log-level", "ERROR", "--log-every", "0",
         "--set", "WIDTH=14", "--set", "HEIGHT=14", "--set", "NUM_AGENTS=3",
         "--set", "BATCH_SIZE=12", "--set", "FIRE_START_STEP=0",
         "--set", "ACTIVATE_FIREFIGHTING=False"]


@pytest.fixture(autouse=True)
def restore_config():
    """Puts config.py back after each test.

    main() applies the overrides in this process as well as in the workers, as its fail-fast check that
    the configuration is valid before a batch starts, and seeding replaces SYSTEM_RANDOM outright when a
    batch runs sequentially. So a run leaks both into whatever runs next.
    """
    saved = {name: getattr(config, name) for name in dir(config) if name.isupper()}
    yield
    for name, value in saved.items():
        setattr(config, name, value)


@pytest.fixture
def run(tmp_path):
    """Runs a batch and returns its results, as the JSON a reader of an experiment would get."""
    counter = [0]

    def _run(*options, expect=0):
        # a fresh path per call, so that a batch which was supposed to fail cannot be read as having
        # succeeded because an earlier one left its results behind
        counter[0] += 1
        output = tmp_path / f"results{counter[0]}.json"
        code = main([*SMALL, "--output", str(output), *options])
        assert code == expect, f"headless.py exited {code}"
        return json.loads(output.read_text()) if output.exists() else None

    return _run


def fingerprint(results):
    """What a batch did, reduced to something that moves if any draw in it moved."""
    return [(result["run_id"], result["seed"], result["steps_completed"],
             round(result["mr1_total"], 9), result["mr2"], result["burning_cells_final"])
            for result in sorted(results, key=lambda result: result["run_id"])]


# --- an explicit seed pins the batch ----------------------------------------


def test_the_same_seed_gives_the_same_batch_in_parallel(run):
    """The contract --seed exists for, exercised where it was at risk: several runs at once."""
    first = run("--runs", "6", "--workers", "4", "--seed", "1")
    second = run("--runs", "6", "--workers", "4", "--seed", "1")

    assert fingerprint(first) == fingerprint(second)


def test_runs_within_a_seeded_batch_differ_from_one_another(run):
    """Run N takes seed+N, so a batch is six different fires rather than one fire six times."""
    results = run("--runs", "6", "--workers", "4", "--seed", "1")

    assert [result["seed"] for result in sorted(results, key=lambda r: r["run_id"])] == [1, 2, 3, 4, 5, 6]
    assert len({result["mr1_total"] for result in results}) > 1


# --- an unseeded batch is independent, and still replayable -----------------


def test_an_unseeded_batch_records_a_real_seed_for_every_run(run):
    """The recording half: 'seed': None used to make an interesting run unrepeatable."""
    results = run("--runs", "4", "--workers", "2")

    seeds = [result["seed"] for result in results]
    assert all(isinstance(seed, int) for seed in seeds)
    assert len(set(seeds)) == len(seeds)


def test_two_unseeded_batches_are_independent(run):
    """The independence half: a fixed default would make every batch the same batch."""
    first = run("--runs", "4", "--workers", "2")
    second = run("--runs", "4", "--workers", "2")

    assert {result["seed"] for result in first}.isdisjoint({result["seed"] for result in second})
    assert fingerprint(first) != fingerprint(second)


def test_a_recorded_seed_replays_its_batch(run):
    """Run 0 takes the base seed, so what a batch recorded is what --seed needs to repeat it.

    This is the point of the whole change: an unseeded batch is free to be random precisely because it
    can still be replayed afterwards from what it wrote down.
    """
    original = run("--runs", "4", "--workers", "2")
    base = min(result["seed"] for result in original)

    replayed = run("--runs", "4", "--workers", "2", "--seed", str(base))

    assert fingerprint(replayed) == fingerprint(original)


# --- threads cannot be parallel ---------------------------------------------


def test_parallel_threads_are_refused(run):
    """The defect itself. Threads share config.SYSTEM_RANDOM, so the runs take each other's fires."""
    assert run("--runs", "6", "--workers", "4", "--executor", "thread", "--seed", "1", expect=2) is None


def test_parallel_threads_are_refused_even_without_a_seed(run):
    """Every batch is seeded now, so there is no unseeded case left in which threads would be safe.

    The check used to be conditional on --seed, which is why this is a test of its own.
    """
    assert run("--runs", "6", "--workers", "4", "--executor", "thread", expect=2) is None


def test_a_single_threaded_worker_is_still_allowed(run):
    """--executor thread is documented as a debugging aid; one worker cannot interleave with anything."""
    assert len(run("--runs", "2", "--workers", "1", "--executor", "thread", "--seed", "1")) == 2
