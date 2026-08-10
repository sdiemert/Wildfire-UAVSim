"""Tests that SYSTEM_RANDOM really is the only source of randomness in the simulation.

config.py documents SYSTEM_RANDOM as the generator every stochastic decision draws from, and both
headless.py --seed and the seed_rng fixture make a run reproducible by replacing it. That only holds if
nothing draws from the bare `random` module behind its back, which the Fire agents used to do for cell
fuel, the spread roll and spontaneous re-ignition.
"""

# python libraries

import random


# --- helpers ----------------------------------------------------------------


def fingerprint(model, steps):
    """Run a model and reduce it to something that changes if any draw changes."""
    for _ in range(steps):
        model.step()
    return (
        [fire.fuel for fire in model.fire_list],
        [fire.burning for fire in model.fire_list],
        [uav.pos for uav in model.uavs],
        [round(uav.fuel, 6) for uav in model.uavs],
        model.MR2_VALUE,
    )


# --- the whole simulation ---------------------------------------------------


def test_two_runs_with_the_same_seed_are_identical(make_model, sim_config):
    """Seeding SYSTEM_RANDOM alone has to pin the entire run."""
    sim_config(SYSTEM_RANDOM=random.Random(1234))
    first = fingerprint(make_model(NUM_AGENTS=3, DENSITY_PROB=0.8), steps=15)

    sim_config(SYSTEM_RANDOM=random.Random(1234))
    second = fingerprint(make_model(NUM_AGENTS=3, DENSITY_PROB=0.8), steps=15)

    assert first == second


def test_two_runs_with_different_seeds_differ(make_model, sim_config):
    """The counterpart: the fingerprint is sensitive enough to be worth checking."""
    sim_config(SYSTEM_RANDOM=random.Random(1))
    first = fingerprint(make_model(NUM_AGENTS=3, DENSITY_PROB=0.8), steps=15)

    sim_config(SYSTEM_RANDOM=random.Random(2))
    second = fingerprint(make_model(NUM_AGENTS=3, DENSITY_PROB=0.8), steps=15)

    assert first != second


def test_a_run_with_positioning_error_is_still_reproducible(make_model, sim_config):
    """Seeding SYSTEM_RANDOM has to pin where each UAV believes it is, as well as where it really is.

    Neither half of a UAV's positioning error is drawn while it flies: the fixed bias comes from
    SYSTEM_RANDOM once when the UAV is created, and the per step jitter is worked out from the UAV and the
    step number by formulas.position_noise(). So collecting the measurements as the run goes along cannot be
    what makes the two runs agree -- asking is free of side effects, which is the point of doing it that way.
    """
    def trace(seed):
        sim_config(SYSTEM_RANDOM=random.Random(seed))
        model = make_model(NUM_AGENTS=3, DENSITY_PROB=0.8, ACTIVATE_POSITION_ERROR=True,
                           UAV_POSITION_BIAS_MAX=2, UAV_POSITION_NOISE_MAX=1)
        measured = []
        for _ in range(15):
            measured.append([uav.measured_pos() for uav in model.uavs])
            model.step()
        return fingerprint(model, steps=0), measured

    first = trace(4321)
    assert first == trace(4321)
    # and the measurements really are moving about, so the equality above is not comparing two dull lists
    assert len({tuple(step) for step in first[1]}) > 1


def test_the_module_random_state_does_not_affect_a_seeded_run(make_model, sim_config):
    """The point of the change: disturbing `random` must not move a seeded simulation.

    Fire.__init__ drew cell fuel from random.randint(), and Fire.step() rolled the spread and the
    spontaneous re-ignition from random.random(), so a run seeded only through SYSTEM_RANDOM was not
    actually reproducible.
    """
    random.seed(0)
    sim_config(SYSTEM_RANDOM=random.Random(99))
    first = fingerprint(make_model(NUM_AGENTS=2, DENSITY_PROB=0.8), steps=15)

    # a different module level state, and plenty of draws taken out of it
    random.seed(777)
    [random.random() for _ in range(1000)]
    sim_config(SYSTEM_RANDOM=random.Random(99))
    second = fingerprint(make_model(NUM_AGENTS=2, DENSITY_PROB=0.8), steps=15)

    assert first == second


def test_a_run_with_smoke_occluding_is_still_reproducible(make_model, sim_config):
    """Seeding SYSTEM_RANDOM has to pin a run the smoke is blinding, as well as a clear one.

    The plume is a fixed function of which cells are smoking and the occlusion is a threshold on it, so
    sim/smoke.py takes nothing from SYSTEM_RANDOM in any wind mode -- unlike sim/fire_spread.py, which
    draws an array per mixed offset per step under composed wind. That is what lets observe() be called any
    number of times in a step without moving the run along.
    """
    settings = dict(NUM_AGENTS=3, DENSITY_PROB=0.8, ACTIVATE_SMOKE=True,
                    SMOKE_OCCLUDES_OBSERVATION=True, SMOKE_DRIFT_RADIUS=5)

    sim_config(SYSTEM_RANDOM=random.Random(1234))
    first = fingerprint(make_model(**settings), steps=15)

    sim_config(SYSTEM_RANDOM=random.Random(1234))
    second = fingerprint(make_model(**settings), steps=15)

    assert first == second


def test_occluding_the_team_costs_the_generator_nothing(make_model, sim_config):
    """With nobody flying, switching occlusion on must not move a single draw.

    Nothing reads the occlusion mask when there are no UAVs and no managing system, so the fire has to
    burn identically either way. A field that drew even one number -- to pick a wind direction per cell, as
    the fire spread does -- would shift every draw after it and the two fires would part company.
    """
    settings = dict(NUM_AGENTS=0, DENSITY_PROB=0.8, ACTIVATE_SMOKE=True, SMOKE_DRIFT_RADIUS=5)

    sim_config(SYSTEM_RANDOM=random.Random(99))
    clear = fingerprint(make_model(SMOKE_OCCLUDES_OBSERVATION=False, **settings), steps=15)

    sim_config(SYSTEM_RANDOM=random.Random(99))
    blind = fingerprint(make_model(SMOKE_OCCLUDES_OBSERVATION=True, **settings), steps=15)

    assert clear == blind


# --- the individual draws ---------------------------------------------------


def test_cell_fuel_is_drawn_from_system_random(make_model, sim_config):
    """Fire.__init__ used random.randint(), which no seeding of SYSTEM_RANDOM could reach."""
    sim_config(SYSTEM_RANDOM=random.Random(5))
    first = [fire.fuel for fire in make_model(NUM_AGENTS=0).fire_list]

    random.seed(31337)  # would change the answer if randint() still came from here
    sim_config(SYSTEM_RANDOM=random.Random(5))
    second = [fire.fuel for fire in make_model(NUM_AGENTS=0).fire_list]

    assert first == second
    # a real spread of values, so the equality above is not comparing two constant lists
    assert len(set(first)) > 1


def test_nothing_draws_from_the_module_random(monkeypatch, make_model):
    """No part of a running simulation may reach the bare `random` module.

    The module itself is booby trapped rather than any one importer of it, so this keeps holding however
    the simulation modules choose to import things.
    """
    def refuse(*args, **kwargs):
        raise AssertionError("the simulation drew from the random module instead of SYSTEM_RANDOM")

    for name in ("random", "randint", "choice", "randrange", "sample", "shuffle"):
        monkeypatch.setattr(random, name, refuse)

    model = make_model(NUM_AGENTS=2, DENSITY_PROB=0.8)
    for _ in range(10):
        model.step()
