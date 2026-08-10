"""Tests for the smoke plume field.

Smoke used to be a countdown owned by each Fire cell, with no spatial extent whatever: a cell either was or
was not smoking, and nothing anywhere read the answer except the canvas. The plume in sim/smoke.py is
therefore new code with no per cell reference implementation to check against, the way
tests/test_fire_spread.py checks the vectorized spread against Fire.probability_of_fire(). What can be
pinned instead is the set of claims the extension is built on, and those are what this file is:

  * the field is a function of the source mask and the settings, and of nothing else -- in particular it
    takes nothing at all from config.SYSTEM_RANDOM, in any wind mode. That is what lets a UAV be asked twice
    in one step what it can see and be told the same thing, and it is why occlusion is a threshold and not
    a roll;
  * the plume goes downwind, further downwind than the fire could ever spread, and it leans harder than the
    fire does at the settings that ship;
  * the new model contains the old one: turn the wind bias and the drift off, and the cells the smoke hides
    are exactly the cells that are raising it.
"""

# python libraries

import numpy
import pytest

# own python modules

import config

from sim import fire_spread, smoke


# --- helpers ----------------------------------------------------------------


# a source mask of the given size with the named cells raising smoke
def sources(size, cells):
    mask = numpy.zeros((size, size), dtype=bool)
    for x, y in cells:
        mask[x, y] = True
    return mask


# the cells a field hides, as a set, which is easier to state a claim about than an array
def hidden(field, mask):
    opaque = field.opaque(mask)
    return {(x, y) for x in range(opaque.shape[0]) for y in range(opaque.shape[1]) if opaque[x, y]}


@pytest.fixture
def southerly(sim_config):
    """A fixed wind blowing south, which is the setting every directional claim below is made against."""
    sim_config(ACTIVATE_WIND=True, FIXED_WIND=True, WIND_DIRECTION="south",
               SMOKE_MU=0.9, SMOKE_DRIFT_RADIUS=6, SMOKE_OCCLUSION_THRESHOLD=0.5)


# --- randomness -------------------------------------------------------------


@pytest.mark.parametrize("fixed", [True, False])
def test_building_and_reading_the_field_takes_nothing_from_the_shared_generator(sim_config, monkeypatch,
                                                                                fixed):
    # the invariant the whole extension rests on. FireSpread draws one array per mixed offset per step under
    # composed wind; this must not, or a run would depend on how many times anything happened to ask a UAV
    # what it could see -- including the status panel between steps
    sim_config(ACTIVATE_WIND=True, FIXED_WIND=fixed, SMOKE_DRIFT_RADIUS=4)

    def refuse(*args, **kwargs):
        raise AssertionError("the smoke field drew from SYSTEM_RANDOM")

    for name in ("random", "randint", "choice", "randrange", "sample", "shuffle", "getrandbits"):
        monkeypatch.setattr(config.SYSTEM_RANDOM, name, refuse)

    field = smoke.SmokeField(11, 11)
    field.opaque(sources(11, [(5, 5)]))


def test_the_same_sources_give_the_same_field_every_time_they_are_asked(sim_config):
    # composed wind is the interesting case: FireSpread redraws the direction per cell per step, and a
    # blended kernel is what replaces that here
    sim_config(ACTIVATE_WIND=True, FIXED_WIND=False, FIRST_DIR="south", SECOND_DIR="east",
               FIRST_DIR_PROB=0.8, SMOKE_DRIFT_RADIUS=4)
    mask = sources(11, [(5, 5), (5, 6)])

    first = smoke.SmokeField(11, 11)
    second = smoke.SmokeField(11, 11)
    assert numpy.array_equal(first.opaque(mask), first.opaque(mask))
    assert numpy.array_equal(first.opaque(mask), second.opaque(mask))


def test_a_blended_kernel_lies_between_the_two_directions_it_blends(sim_config):
    # what "the smoke sits in the average of the wind" comes to: no offset gets more weight than the
    # direction that favours it most, or less than the one that favours it least
    sim_config(ACTIVATE_WIND=True, FIXED_WIND=False, FIRST_DIR="south", SECOND_DIR="east",
               FIRST_DIR_PROB=0.6, SMOKE_MU=0.9, SMOKE_DRIFT_RADIUS=4)
    blended = smoke.SmokeField(11, 11).kernel
    south = smoke.build_smoke_kernel(4, 0.9, "south")
    east = smoke.build_smoke_kernel(4, 0.9, "east")

    assert numpy.all(blended <= numpy.maximum(south, east) + 1e-12)
    assert numpy.all(blended >= numpy.minimum(south, east) - 1e-12)


# --- the shape of a plume ---------------------------------------------------


@pytest.mark.parametrize("threshold", [0.01, 0.5, 1.0])
def test_a_cell_raising_smoke_is_always_hidden_by_it(sim_config, threshold):
    # K[0, 0] is set to 1 outright, because cell_weight() answers 0 at distance 0: it is written for a fire
    # deciding whether a neighbour lights it, and no cell lights itself
    sim_config(SMOKE_OCCLUSION_THRESHOLD=threshold, SMOKE_DRIFT_RADIUS=3)
    field = smoke.SmokeField(11, 11)
    assert (5, 5) in hidden(field, sources(11, [(5, 5)]))


def test_with_the_drift_switched_off_the_hidden_cells_are_exactly_the_smoking_ones(sim_config):
    # the anchor that says the new model contains the old one: at zero drift the plume degenerates to the
    # per cell smoke that sim/environment.py has always kept
    sim_config(SMOKE_DRIFT_RADIUS=0, SMOKE_OCCLUSION_THRESHOLD=0.5)
    field = smoke.SmokeField(11, 11)
    smoking = [(5, 5), (2, 8), (9, 1)]
    assert hidden(field, sources(11, smoking)) == set(smoking)


def test_smoke_drifts_downwind_of_the_cell_that_raised_it(southerly):
    # 'south' is dy > 0 in on_wind(), and the shift in density() reads the source at +offset, so a cell is
    # smoked by sources at higher y: the plume runs to lower y
    field = smoke.SmokeField(15, 15)
    cells = hidden(field, sources(15, [(7, 10)]))

    assert all(y <= 10 for _, y in cells), "smoke reached upwind of its source"
    assert (7, 4) in cells, "the plume did not reach SMOKE_DRIFT_RADIUS downwind"
    assert (7, 3) not in cells, "the plume reached past SMOKE_DRIFT_RADIUS"


def test_smoke_reaches_further_downwind_than_the_fire_can_spread(southerly):
    # the headline claim of the extension, and the reason it is a separate module rather than a recolour of
    # the fire. The fire's kernel is built for radius 3 and is exactly zero past it, whatever the wind
    field = smoke.SmokeField(15, 15)
    smoke_reach = 10 - min(y for _, y in hidden(field, sources(15, [(7, 10)])))

    # the fire's kernel is built for radius 3 and is exactly zero at every offset past it, downwind or not
    fire_reach = (fire_spread.build_kernel(3, config.MU, "south").shape[0] - 1) // 2

    assert smoke_reach == config.SMOKE_DRIFT_RADIUS
    assert smoke_reach > fire_reach


def test_the_smoke_leans_harder_on_the_wind_than_the_fire_does_at_the_shipped_settings(southerly):
    # 'more impacted by wind than the fire' in the one form that can be measured: the ratio of the weight
    # given to a cell downwind and one the same distance crosswind. Note this comes from SMOKE_MU being
    # above MU and not from a different wind law -- the two share cell_weight(), so at equal mu they agree,
    # which the next test pins
    smoke_kernel = smoke.build_smoke_kernel(3, config.SMOKE_MU, "south")
    fire_kernel_weight = fire_spread.cell_weight

    def skew(weight_at):
        return weight_at(0, 2) / weight_at(2, 0)

    smoke_skew = smoke_kernel[3, 5] / smoke_kernel[5, 3]
    fire_skew = skew(lambda dx, dy: fire_kernel_weight(dx, dy, 3, config.MU, "south"))
    assert smoke_skew > fire_skew


@pytest.mark.parametrize("direction", ["north", "south", "east", "west"])
def test_the_smoke_and_the_fire_agree_about_which_way_is_downwind(direction):
    # the guard on the decision that there is one wind model with two consumers. cell_weight() and
    # on_wind() are imported from sim/fire_spread.py rather than restated, so given the same strength and
    # the same radius the two kernels are the same kernel. This test is what fails when somebody forks them
    smoke_kernel = smoke.build_smoke_kernel(3, 0.5, direction)
    fire_weights = numpy.array([[fire_spread.cell_weight(dx, dy, 3, 0.5, direction)
                                 for dy in range(-3, 4)] for dx in range(-3, 4)])

    # the centre is the one deliberate difference: a source is in its own smoke, a fire does not light itself
    smoke_kernel[3, 3] = fire_weights[3, 3]
    assert numpy.allclose(smoke_kernel, fire_weights)


def test_a_plume_is_as_wide_as_the_front_that_raises_it(southerly):
    # a lone source casts a column one cell wide, which is only a wart in isolation: every cell of a burning
    # front casts its own, and the union is a plume the width of the front
    field = smoke.SmokeField(21, 21)
    lone = hidden(field, sources(21, [(10, 14)]))
    front = hidden(field, sources(21, [(x, 14) for x in range(8, 13)]))

    def width(cells):
        return len({x for x, _ in cells})

    assert width(lone) == 1
    assert width(front) == 5
    assert lone < front


def test_a_density_never_passes_one_however_many_cells_are_smoking(southerly):
    # the clip. Several sources reaching one cell make it opaque, not more than opaque, which is what keeps
    # SMOKE_OCCLUSION_THRESHOLD readable as a fraction rather than as an unbounded count
    field = smoke.SmokeField(15, 15)
    everywhere = numpy.ones((15, 15), dtype=bool)
    assert field.density(everywhere).max() <= 1.0


def test_lowering_the_threshold_can_only_hide_more(southerly, sim_config):
    # monotonicity, rather than a magic number: the knob is documented as "lower means a wider plume"
    mask = sources(21, [(x, 14) for x in range(9, 12)])
    wide = smoke.SmokeField(21, 21, threshold=0.05)
    narrow = smoke.SmokeField(21, 21, threshold=0.9)
    assert hidden(narrow, mask) < hidden(wide, mask)


def test_with_no_wind_at_all_the_plume_is_symmetric_about_its_source(sim_config):
    sim_config(ACTIVATE_WIND=False, SMOKE_DRIFT_RADIUS=4, SMOKE_OCCLUSION_THRESHOLD=0.2)
    field = smoke.SmokeField(15, 15)
    cells = hidden(field, sources(15, [(7, 7)]))

    assert {(14 - x, y) for x, y in cells} == cells
    assert {(x, 14 - y) for x, y in cells} == cells
