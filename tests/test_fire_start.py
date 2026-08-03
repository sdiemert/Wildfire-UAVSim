"""Tests for where and when the initial wildfire starts.

FIRE_START_POSITION and FIRE_START_STEP each accept several forms, so these check that every form is
honoured, that the defaults still light the centre of the grid before the first step, and that a delayed
fire really does leave the grid unburnt until its step arrives.
"""

# python libraries

import random

import pytest

# own python modules

from sim import agents


# --- helpers ----------------------------------------------------------------


def burning_cells(model):
    return [agent.pos for agent in model.schedule.agents
            if type(agent) is agents.Fire and agent.is_burning()]


def seeded(seed):
    """A generator to hand to make_model as SYSTEM_RANDOM, so the random choices are reproducible."""
    return random.Random(seed)


# --- where the fire starts --------------------------------------------------


def test_the_default_lights_the_centre_of_the_grid(make_model):
    model = make_model(NUM_AGENTS=0)
    assert model.fire_start_pos == (4, 4)
    assert burning_cells(model) == [(4, 4)]


def test_a_specified_position_is_honoured(make_model):
    model = make_model(NUM_AGENTS=0, FIRE_START_POSITION=(1, 7))
    assert model.fire_start_pos == (1, 7)
    assert burning_cells(model) == [(1, 7)]


def test_a_random_position_lands_on_the_grid(make_model):
    seen = set()
    for seed in range(10):
        model = make_model(NUM_AGENTS=0, FIRE_START_POSITION="random", SYSTEM_RANDOM=seeded(seed))
        x, y = model.fire_start_pos
        assert 0 <= x < 9 and 0 <= y < 9
        assert burning_cells(model) == [model.fire_start_pos]
        seen.add(model.fire_start_pos)
    # a single fixed cell would mean the draw is not random at all
    assert len(seen) > 1


def test_a_random_position_avoids_the_home_base(make_model):
    # the base covers most of a tiny grid, so a fire lit on it would be very likely without the guard
    for seed in range(20):
        model = make_model(WIDTH=3, HEIGHT=3, NUM_AGENTS=0, NUM_OUT_BUILDINGS=0,
                           ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(0, 0), BASE_SIZE=(2, 2),
                           FIRE_START_POSITION="random", SYSTEM_RANDOM=seeded(seed))
        assert model.fire_start_pos not in model.base.cells
        assert not model.base.is_burning()


def test_the_ignition_cell_exists_even_where_nothing_grows(make_model):
    # no tree is placed anywhere, but the fire still needs a cell to start from
    model = make_model(NUM_AGENTS=0, DENSITY_PROB=0, FIRE_START_POSITION=(6, 2))
    assert model.fire_agent_at((6, 2)) is not None
    assert model.fire_agent_at((0, 0)) is None
    assert burning_cells(model) == [(6, 2)]


def test_a_position_outside_the_grid_is_rejected(make_model):
    with pytest.raises(ValueError, match="outside"):
        make_model(NUM_AGENTS=0, FIRE_START_POSITION=(9, 9))


def test_an_unknown_position_setting_is_rejected(make_model):
    with pytest.raises(ValueError, match="FIRE_START_POSITION"):
        make_model(NUM_AGENTS=0, FIRE_START_POSITION="somewhere")


# --- when the fire starts ---------------------------------------------------


def test_the_default_burns_from_the_start(make_model):
    model = make_model(NUM_AGENTS=0)
    assert model.fire_start_step == 0
    assert model.fire_started
    assert burning_cells(model)


def test_a_delayed_fire_leaves_the_grid_unburnt_until_its_step(make_model):
    # FIRE_SPREAD_SPEED is pinned above 1 so that the ignition cell is still alight when it is checked:
    # a cell that updates every step lights its neighbours and burns down within the step it was lit in
    model = make_model(NUM_AGENTS=0, FIRE_START_POSITION=(4, 4), FIRE_START_STEP=3, FIRE_SPREAD_SPEED=2)
    assert model.fire_start_step == 3
    assert not model.fire_started
    assert burning_cells(model) == []

    for _ in range(3):
        assert not model.fire_started
        model.step()

    assert model.fire_started
    assert (4, 4) in burning_cells(model)


def test_a_delayed_fire_spreads_once_it_is_lit(make_model):
    model = make_model(NUM_AGENTS=0, FIRE_START_POSITION=(4, 4), FIRE_START_STEP=2,
                       FIRE_SPREAD_SPEED=1)
    for _ in range(5):
        model.step()
    # the neighbours of the ignition cell saw it burning and caught fire in their turn
    assert len(burning_cells(model)) > 1


def test_a_step_range_is_drawn_from_inside_the_range(make_model):
    drawn = set()
    for seed in range(15):
        model = make_model(NUM_AGENTS=0, FIRE_START_STEP=(5, 9), SYSTEM_RANDOM=seeded(seed))
        assert 5 <= model.fire_start_step <= 9
        assert not model.fire_started
        drawn.add(model.fire_start_step)
    assert len(drawn) > 1


def test_a_random_step_stays_inside_the_run(make_model):
    for seed in range(15):
        model = make_model(NUM_AGENTS=0, BATCH_SIZE=20, FIRE_START_STEP="random",
                           SYSTEM_RANDOM=seeded(seed))
        assert 0 <= model.fire_start_step < 20


def test_a_backwards_range_is_rejected(make_model):
    with pytest.raises(ValueError, match="ends before it starts"):
        make_model(NUM_AGENTS=0, FIRE_START_STEP=(9, 4))


def test_an_unknown_step_setting_is_rejected(make_model):
    with pytest.raises(ValueError, match="FIRE_START_STEP"):
        make_model(NUM_AGENTS=0, FIRE_START_STEP="soon")


# --- the two settings together ----------------------------------------------


def test_the_uavs_fly_before_the_fire_starts(make_model):
    # nothing to monitor yet, so the run is simply uneventful rather than broken
    model = make_model(NUM_AGENTS=2, FIRE_START_STEP=4)
    for _ in range(3):
        model.step()

    assert model.running
    assert burning_cells(model) == []
    assert model.MR2_VALUE >= 0
    assert all(score == 0.0 for score in model.MR1_LIST)


def test_a_delayed_fire_cannot_destroy_the_base_beforehand(make_model):
    # the base sits on the ignition cell, and still survives while the fire is pending
    model = make_model(ACTIVATE_FIREFIGHTING=True, NUM_AGENTS=0, NUM_OUT_BUILDINGS=0,
                       BASE_POSITION=(4, 4), BHP=1, FIRE_START_POSITION=(4, 4), FIRE_START_STEP=5)
    for _ in range(4):
        model.step()
    assert not model.lost

    model.step()  # the fire is lit under the base
    model.step()
    assert model.lost
