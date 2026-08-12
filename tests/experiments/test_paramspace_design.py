"""Tests for the parameter space sweep's design and the invariant its runner depends on.

The scripts under experiments/ are one-off analysis and are not generally tested. Two things in
experiments/20260811_paramspace/ are exceptions, because both fail *silently* and both would produce a
plausible looking report full of wrong numbers.

The first is the runner's override invariant. Unlike tools/sweep.py, which isolates every arm in its own
headless.py subprocess, run.py submits the whole sweep to one process pool. apply_overrides() sets
attributes on the global config module and resets nothing, and pool workers are reused, so a setting that
one arm overrides and another does not would leak from the first arm into the second -- silently, since
the run still completes and still writes a number. run.py refuses to submit a batch whose configs do not
all override the same keys; these tests pin that refusal and check the design actually satisfies it.

The second is the design itself. config.validate() catches an arm that violates a bound, but only when
that arm is reached, which on a multi-hour sweep can be two hours in. Every arm is validated here in a
second instead. FUEL_BOTTOM_LIMIT <= FUEL_UPPER_LIMIT is the constraint that motivated this: the design
satisfies it by construction rather than by rejection, and "by construction" is a claim worth testing.
"""

# python libraries

import importlib.util
import pathlib
import sys

import pytest

# own python modules

import config

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
EXPERIMENT = REPO_ROOT / "experiments" / "20260811_paramspace"


def _load(name):
    """Import a module from the experiment directory.

    Loaded by path rather than by import: experiments/ is not a package, and the scripts there import
    each other as plain top-level modules after inserting the repository root on sys.path.
    """
    if str(EXPERIMENT) not in sys.path:
        sys.path.insert(0, str(EXPERIMENT))
    spec = importlib.util.spec_from_file_location(name, EXPERIMENT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def design():
    return _load("design")


@pytest.fixture(scope="module")
def arms(design):
    return design.build_arms()


@pytest.fixture(scope="module")
def runner():
    return _load("run")


# --- the design -------------------------------------------------------------


def test_the_design_has_the_number_of_arms_it_claims(design, arms):
    assert len(arms) == design.N_ARMS


def test_the_design_is_a_power_of_two_because_sobol_needs_one(design):
    # scipy's Sobol engine only guarantees its balance properties at powers of two, and warns otherwise.
    # A design silently losing its uniformity is exactly the kind of thing nobody notices.
    assert design.N_ARMS & (design.N_ARMS - 1) == 0


def test_the_design_is_reproducible_from_its_seed_alone(design):
    # design.json is gitignored, so the design has to be rebuildable from the committed script. Two
    # builds at the same seed must agree, or the analysis cannot be joined back onto the runs.
    first = design.build_arms(n_arms=64, seed=99)
    second = design.build_arms(n_arms=64, seed=99)
    assert [arm["params"] for arm in first] == [arm["params"] for arm in second]


def test_a_different_seed_gives_a_different_design(design):
    first = design.build_arms(n_arms=64, seed=99)
    second = design.build_arms(n_arms=64, seed=100)
    assert [arm["params"] for arm in first] != [arm["params"] for arm in second]


def test_fuel_limits_are_ordered_in_every_arm(design, arms):
    # The constraint config.validate() enforces. The design satisfies it by drawing the upper limit from
    # the bottom limit upwards, rather than by sampling a square and rejecting half of it, so this test
    # is what says the construction is actually doing what it claims.
    for arm in arms:
        params = arm["params"]
        assert 1 <= params["FUEL_BOTTOM_LIMIT"] <= params["FUEL_UPPER_LIMIT"], arm["slug"]
        assert params["FUEL_UPPER_LIMIT"] <= design.FUEL_UPPER_CEILING, arm["slug"]


def test_every_swept_parameter_stays_inside_its_declared_range(design, arms):
    for arm in arms:
        for name, (low, high, _) in design.RANGES.items():
            assert low <= arm["params"][name] <= high, f"{arm['slug']}: {name}"


def test_the_wind_directions_are_exactly_balanced(design, arms):
    # Stratified, not sampled: an unbalanced design would confound wind direction with everything else
    # the Sobol sequence happened to put alongside it.
    counts = {direction: 0 for direction in design.COMPASS}
    for arm in arms:
        counts[arm["params"]["WIND_DIRECTION"]] += 1
    assert set(counts.values()) == {design.N_ARMS // len(design.COMPASS)}


def test_every_wind_direction_is_one_the_simulation_knows(design, arms):
    for arm in arms:
        assert arm["params"]["WIND_DIRECTION"] in config.WIND_HEADINGS, arm["slug"]
        # the simulation reads a list; a bare string is accepted but records itself differently
        assert arm["settings"]["WIND_DIRECTION"] == [arm["params"]["WIND_DIRECTION"]]


def test_the_slugs_are_unique(design, arms):
    # the slug is the results filename, so a collision would have one arm overwrite another's runs
    slugs = {arm["slug"] for arm in arms}
    assert len(slugs) == len(arms)


def test_every_arm_validates_as_a_configuration(design, arms, monkeypatch):
    """Every arm passes config.validate(), checked here rather than two hours into the sweep.

    validate() reads the module globals, so the settings have to actually be applied. monkeypatch puts
    them back afterwards, which matters because config is a module and every other test in the session
    shares it.
    """
    for name, value in list(config.__dict__.items()):
        if name.isupper():
            monkeypatch.setattr(config, name, value, raising=False)

    for arm in arms:
        for name, value in arm["settings"].items():
            monkeypatch.setattr(config, name, value, raising=False)
        # raises ValueError listing everything wrong with the combination
        config.validate()


# --- the constants ----------------------------------------------------------


def test_the_constants_make_a_loss_measurable(design):
    """Without a base there is nothing to lose, and every run scores N/A instead of WON or LOST."""
    assert design.CONSTANTS["ACTIVATE_FIREFIGHTING"] is True
    assert design.CONSTANTS["NUM_AGENTS"] == 0
    assert design.CONSTANTS["MANAGING_SYSTEM"] == "none"


def test_no_swept_parameter_is_also_pinned_as_a_constant(design, arms):
    # A parameter in both places would be swept in name and constant in fact, and the report would
    # describe a sweep that never happened.
    swept = set(design.DIMENSIONS) | {"WIND_DIRECTION"}
    assert swept.isdisjoint(set(design.CONSTANTS) - {"WIND_DIRECTION"})
    # WIND_DIRECTION is the one overlap, and the arm must win it
    assert arms[0]["settings"]["WIND_DIRECTION"] == [arms[0]["params"]["WIND_DIRECTION"]]


# --- the runner's override invariant ----------------------------------------


def test_every_config_overrides_the_same_keys(runner, arms):
    """The invariant the whole single-pool design rests on. See the module docstring."""
    configs = runner.build_configs(arms[:8], runs_per_arm=3, seed_base=1)
    keys = {frozenset(config.overrides) for config in configs}
    assert len(keys) == 1, "arms override different sets of constants; settings would leak between them"


def test_every_config_overrides_every_swept_parameter(runner, design, arms):
    configs = runner.build_configs(arms[:8], runs_per_arm=1, seed_base=1)
    for config_ in configs:
        for name in (*design.DIMENSIONS, "WIND_DIRECTION"):
            assert name in config_.overrides


def test_every_config_overrides_every_constant(runner, design, arms):
    configs = runner.build_configs(arms[:8], runs_per_arm=1, seed_base=1)
    for config_ in configs:
        for name in design.CONSTANTS:
            assert name in config_.overrides


def test_the_uniformity_check_rejects_a_config_missing_a_key(runner, arms):
    """The check has to actually fail on the thing it exists to catch."""
    configs = runner.build_configs(arms[:2], runs_per_arm=1, seed_base=1)
    del configs[1].overrides["DENSITY_PROB"]
    with pytest.raises(SystemExit, match="different set of constants"):
        runner.assert_uniform_overrides(configs)


def test_the_uniformity_check_rejects_a_config_with_an_extra_key(runner, arms):
    configs = runner.build_configs(arms[:2], runs_per_arm=1, seed_base=1)
    configs[1].overrides["UAV_SPEED"] = 3
    with pytest.raises(SystemExit, match="different set of constants"):
        runner.assert_uniform_overrides(configs)


def test_the_uniformity_check_passes_the_real_design(runner, arms):
    runner.assert_uniform_overrides(runner.build_configs(arms, runs_per_arm=1, seed_base=1))


def test_arms_are_paired_on_the_fire(runner, arms):
    """Run i of every arm draws the same seed, which is what makes two arms comparable."""
    configs = runner.build_configs(arms[:4], runs_per_arm=5, seed_base=500)
    by_arm = {}
    for config_ in configs:
        by_arm.setdefault(config_.run_id // 5, []).append(config_.seed)
    assert len({tuple(seeds) for seeds in by_arm.values()}) == 1
    assert by_arm[0] == [500, 501, 502, 503, 504]


def test_seeds_are_distinct_within_an_arm(runner, arms):
    # paired across arms, independent within one: 100 copies of the same fire would not be 100 runs
    configs = runner.build_configs(arms[:1], runs_per_arm=20, seed_base=500)
    seeds = [config_.seed for config_ in configs]
    assert len(set(seeds)) == len(seeds)


def test_run_ids_are_globally_unique(runner, arms):
    # run_batch sorts on run_id and _collect keys crashed runs by it, so a collision would silently
    # attribute one arm's failure to another
    configs = runner.build_configs(arms[:16], runs_per_arm=7, seed_base=1)
    ids = [config_.run_id for config_ in configs]
    assert len(set(ids)) == len(ids)


def test_the_step_count_matches_the_batch_size(runner, design, arms):
    """RunConfig.steps is the loop bound and BATCH_SIZE is what the model stops on.

    They have to be the same number. When they were not, a run truncated below BATCH_SIZE was scored as
    won -- see the note in sim/cli/main.py, which is why headless.py folds --steps into the overrides
    rather than counting separately.
    """
    configs = runner.build_configs(arms[:4], runs_per_arm=1, seed_base=1)
    for config_ in configs:
        assert config_.steps == config_.overrides["BATCH_SIZE"] == design.CONSTANTS["BATCH_SIZE"]
