"""Checks the wind: which direction blows, and when it turns.

The wind used to be a coin toss between FIRST_DIR and SECOND_DIR taken afresh for every cell and every
neighbour of it, which meant two adjacent cells could feel the wind blowing different ways at the same
instant and no cell ever felt the diagonal the pair was supposed to compose. It is now a single direction
over the whole grid, drawn from WIND_DIRECTION and held for WIND_VARIABILITY steps.

Three properties are worth pinning down, and each of them has a way of going wrong quietly:

  * a single direction list costs nothing from SYSTEM_RANDOM. Draw for it and every seeded run in the
    repository shifts by one number, including the results recorded under experiments/;
  * the direction is held for exactly WIND_VARIABILITY steps, not one more or one fewer -- an off by one
    here is invisible in any run and wrong in every one of them;
  * the fire and the smoke are handed the same direction on the same step. They meet only in
    WildFireModel.step(), which builds one field either side of the scheduler.
"""

# python libraries

import collections

import pytest

# own python modules

import config

from sim import environment


ALL_EIGHT = ("NORTH", "NORTH_EAST", "EAST", "SOUTH_EAST",
             "SOUTH", "SOUTH_WEST", "WEST", "NORTH_WEST")


# ---------------------------------------------------------------------------
# resolving the setting
# ---------------------------------------------------------------------------


def test_a_singleton_list_blows_that_direction_for_the_whole_run(sim_config):
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=["SOUTH"], WIND_VARIABILITY=1)

    wind = environment.Wind()
    assert wind.wind_direction == "SOUTH"
    assert not wind.is_variable()
    for _ in range(50):
        wind.step()
    assert wind.wind_direction == "SOUTH"
    assert wind.redraws == 0


# the invariant the whole repository's seeded results rest on: a wind that cannot vary takes nothing from
# the stream, so a fixed wind run reproduces results recorded before the wind could turn at all
@pytest.mark.parametrize("settings", (
    {"ACTIVATE_WIND": True, "WIND_DIRECTION": ["SOUTH"]},
    {"ACTIVATE_WIND": True, "WIND_DIRECTION": []},
    {"ACTIVATE_WIND": False, "WIND_DIRECTION": ["SOUTH", "EAST"]},
))
def test_a_wind_that_cannot_vary_draws_no_randomness(settings, sim_config, seed_rng):
    sim_config(WIND_VARIABILITY=1, **settings)
    rng = seed_rng(0)
    before = rng.random()

    rng = seed_rng(0)
    wind = environment.Wind()
    for _ in range(20):
        wind.step()

    assert seed_rng and rng.random() == before, "the wind consumed a draw it should not have"


@pytest.mark.parametrize("setting", (None, [], ()))
def test_an_empty_direction_list_means_no_wind(setting, sim_config):
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=setting)

    wind = environment.Wind()
    assert wind.wind_direction is None
    assert wind.directions == ()
    # nothing is downwind of anything when there is no wind
    assert not wind.is_on_wind_direction((5, 5), (5, 6))


def test_activate_wind_off_overrides_the_direction_list(sim_config):
    sim_config(ACTIVATE_WIND=False, WIND_DIRECTION=["SOUTH", "EAST"])
    assert environment.Wind().wind_direction is None


# lower case is what config.py shipped for years and what the sweeps under experiments/ still pass
def test_direction_names_are_normalised(sim_config):
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=["south", "South_West"])
    assert set(environment.Wind().directions) == {"SOUTH", "SOUTH_WEST"}


# a bare string is what --set WIND_DIRECTION=SOUTH produces, since it is not a Python literal
def test_a_bare_string_is_taken_as_a_list_of_one(sim_config):
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION="SOUTH")
    wind = environment.Wind()
    assert wind.directions == ("SOUTH",)
    assert wind.wind_direction == "SOUTH"


# ---------------------------------------------------------------------------
# turning
# ---------------------------------------------------------------------------


def test_the_direction_is_held_for_exactly_the_variability(sim_config, seed_rng):
    seed_rng(7)
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=list(ALL_EIGHT), WIND_VARIABILITY=5)

    wind = environment.Wind()
    for step in range(1, 21):
        wind.step()
        # five steps per direction, so a draw has happened on exactly the multiples of five
        assert wind.redraws == step // 5, f"after {step} step(s)"


def test_variability_of_none_draws_once_and_holds_it(sim_config, seed_rng):
    seed_rng(3)
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=list(ALL_EIGHT), WIND_VARIABILITY=None)

    wind = environment.Wind()
    opening = wind.wind_direction
    assert opening in ALL_EIGHT
    for _ in range(500):
        wind.step()
    assert wind.wind_direction == opening
    assert wind.redraws == 0


# the draw is uniform over the list, and over the list alone: a direction that was not asked for must
# never blow, which is what makes a two direction wind a genuine restriction rather than a hint
def test_the_draw_is_uniform_over_the_configured_list(sim_config, seed_rng):
    seed_rng(11)
    wanted = ["NORTH", "SOUTH_EAST", "WEST"]
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=wanted, WIND_VARIABILITY=1)

    wind = environment.Wind()
    seen = collections.Counter()
    for _ in range(3000):
        wind.step()
        seen[wind.wind_direction] += 1

    assert set(seen) == set(wanted)
    for direction in wanted:
        assert 800 < seen[direction] < 1200, f"{direction} came up {seen[direction]} times in 3000"


# ---------------------------------------------------------------------------
# what downwind means
# ---------------------------------------------------------------------------


# a direction names where the wind blows toward, with y increasing north, so the cell that lights you is
# the one the wind came over on its way. Spelled out here rather than derived, because the heading table
# is the thing under test and a test that recomputed it would agree with any mistake in it.
@pytest.mark.parametrize("direction, igniting_neighbour", (
    ("NORTH", (5, 4)),
    ("SOUTH", (5, 6)),
    ("EAST", (4, 5)),
    ("WEST", (6, 5)),
    ("NORTH_EAST", (4, 4)),
    ("NORTH_WEST", (6, 4)),
    ("SOUTH_EAST", (4, 6)),
    ("SOUTH_WEST", (6, 6)),
))
def test_the_igniting_neighbour_is_the_one_upwind(direction, igniting_neighbour, sim_config):
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=[direction])
    wind = environment.Wind()
    cell = (5, 5)

    assert wind.is_on_wind_direction(cell, igniting_neighbour)
    # and it is the only neighbour of the eight that qualifies
    neighbours = [(cell[0] + dx, cell[1] + dy)
                  for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]
    on_wind = [pos for pos in neighbours if wind.is_on_wind_direction(cell, pos)]
    assert on_wind == [igniting_neighbour]


# a diagonal must not let its two flanking cardinals through. This is the mistake a pair of independent
# per axis checks makes, and it would silently widen every diagonal wind into a three way cone.
def test_a_diagonal_does_not_admit_the_cardinals_beside_it(sim_config):
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=["SOUTH_EAST"])
    wind = environment.Wind()
    cell = (5, 5)

    assert wind.is_on_wind_direction(cell, (4, 6))
    assert not wind.is_on_wind_direction(cell, (5, 6)), "the southerly flank leaked through"
    assert not wind.is_on_wind_direction(cell, (4, 5)), "the easterly flank leaked through"
    # nor may an offset that is a whole number of steps on one axis and not the other
    assert not wind.is_on_wind_direction(cell, (3, 6))


# ---------------------------------------------------------------------------
# the wind as the model sees it
# ---------------------------------------------------------------------------


# the fire field is built before the scheduler runs and the smoke field after it. If the wind turned in
# between, a step would smoke in a direction it never burned in.
def test_the_fire_and_the_smoke_of_a_step_share_one_direction(make_model):
    model = make_model(HEIGHT=20, WIDTH=20, ACTIVATE_WIND=True,
                       WIND_DIRECTION=["NORTH", "SOUTH", "EAST", "WEST"], WIND_VARIABILITY=1,
                       ACTIVATE_SMOKE=True, SMOKE_OCCLUDES_OBSERVATION=True,
                       ACTIVATE_FIREFIGHTING=False)

    # both fields are recorded as they are built. The wind turns at the top of step(), so the direction to
    # compare against is not the one standing before the call -- it is whatever the fire was given, which
    # the smoke after the scheduler then has to match.
    seen = []
    build_fire, build_smoke = model.update_fire_probabilities, model.update_smoke

    def record_fire():
        seen.append(["fire", model.wind.wind_direction])
        build_fire()

    def record_smoke():
        seen[-1].append(model.wind.wind_direction)
        build_smoke()

    model.update_fire_probabilities = record_fire
    model.update_smoke = record_smoke
    for _ in range(10):
        model.step()

    assert len(seen) == 10
    for _, fire_direction, smoke_direction in seen:
        assert fire_direction == smoke_direction, "the wind turned part way through a step"
    # and the wind really was turning, or this proves nothing at all
    assert len({row[1] for row in seen}) > 1


def test_the_model_reports_the_wind_it_drew(make_model):
    model = make_model(ACTIVATE_WIND=True, WIND_DIRECTION=["SOUTH_WEST"])
    assert model.wind_initial == "SOUTH_WEST"
    assert model.wind.wind_direction == "SOUTH_WEST"


# a turning wind has to survive a whole run without the kernels going stale, which is what building one
# per direction up front buys. A run that turns every step exercises every one of them.
def test_a_run_survives_a_wind_that_turns_every_step(make_model):
    model = make_model(HEIGHT=20, WIDTH=20, BATCH_SIZE=40, ACTIVATE_WIND=True,
                       WIND_DIRECTION=list(ALL_EIGHT), WIND_VARIABILITY=1,
                       ACTIVATE_FIREFIGHTING=False)
    for _ in range(40):
        model.step()

    assert model.wind.redraws == 40
    assert model.fire_prob.min() >= 0.0 and model.fire_prob.max() <= 1.0
    assert set(model.fire_spread.kernels) == {None, *ALL_EIGHT}
