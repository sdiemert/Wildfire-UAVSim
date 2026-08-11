"""Checks the vectorized fire spread against the per cell definition it replaced.

sim/fire_spread.py works out the ignition probability of every cell in one convolution, where
Fire.probability_of_fire() (sim/agents/fire.py) works out one cell at a time by walking its neighbourhood.
The two have to agree, so every test here compares them directly on a live model: the per cell
version is the specification, the vectorized one is the implementation under test.

The comparison is made to 1e-12 rather than exactly, because summing logarithms and multiplying
probabilities do not round identically. Observed differences are around 3e-16.
"""

# python libraries

import math

import numpy
import pytest

# own python modules

import config

from sim import fire_spread, formulas


TOLERANCE = 1e-12

# every direction the wind can blow, cardinals and diagonals alike. Taken from config.py rather than
# restated, so that adding a ninth direction there cannot leave these tests quietly checking eight.
WIND_DIRECTIONS = config.WIND_DIRECTIONS


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


# runs the model until enough cells are alight for the comparison to be meaningful. The ignition
# step is configurable and may be delayed, so this steps rather than assuming the fire is burning.
def burn_for_a_while(model, wanted=25, limit=400):
    from sim import agents as agents_module, environment

    fires = [agent for agent in model.schedule.agents if type(agent) is agents_module.Fire]
    for _ in range(limit):
        model.step()
        if sum(fire.burning for fire in fires) >= wanted:
            return fires
    raise AssertionError(f"the fire never reached {wanted} burning cells")


# the per cell probabilities, laid out on the grid the way fire_spread returns them
def reference_field(model, fires):
    field = numpy.zeros((config.HEIGHT, config.WIDTH))
    for fire in fires:
        field[fire.pos] = fire.probability_of_fire()
    return field


# the vectorized probabilities, masked to the cells that actually hold vegetation, because the
# reference is only defined where a Fire agent exists
def vectorized_field(model, fires):
    model.burning[model.fire_xs, model.fire_ys] = [fire.burning for fire in fires]
    # the same direction the reference gets: probability_of_fire() consults model.wind, so handing the
    # convolution anything else would compare two different winds and call the difference an error
    computed = model.fire_spread.probability_field(model.burning, model.wind.wind_direction)

    field = numpy.zeros((config.HEIGHT, config.WIDTH))
    for fire in fires:
        field[fire.pos] = 0.0 if fire.fuel <= 0 else computed[fire.pos]
    return field


# builds a model, burns it in, and returns the largest disagreement between the two implementations
def worst_disagreement(make_model, **overrides):
    model = make_model(**overrides)
    fires = burn_for_a_while(model)
    difference = numpy.abs(vectorized_field(model, fires) - reference_field(model, fires))
    return difference.max(), int(model.burning.sum())


# ---------------------------------------------------------------------------
# the kernel itself
# ---------------------------------------------------------------------------


# the kernel has to reproduce distance_rate() exactly, including dropping the corners of the Moore
# window, which lie further away than the radius and so contribute nothing today
@pytest.mark.parametrize("radius", (1, 2, 3, 4))
def test_kernel_matches_distance_rate_without_wind(radius):
    kernel = fire_spread.build_kernel(radius, config.MU)

    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx == 0 and dy == 0:
                # get_neighborhood(include_center=False) never offers a cell itself, and
                # distance_rate() is not defined there: it divides by a distance of zero
                assert kernel[radius, radius] == 0
                continue
            weight = formulas.distance_rate((0, 0), (dx, dy), radius)
            entry = kernel[dx + radius, dy + radius]
            if weight <= 0:
                assert entry == 0, f"offset {(dx, dy)} should not contribute"
            elif weight >= 1.0:
                assert entry == fire_spread.NEG_INF, f"offset {(dx, dy)} should force ignition"
            else:
                assert entry == pytest.approx(math.log1p(-weight), abs=1e-15)


# with the wind on, the kernel has to reproduce distance_rate() composed with Wind.apply_wind()
@pytest.mark.parametrize("direction", WIND_DIRECTIONS)
def test_kernel_matches_apply_wind(direction, sim_config):
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=[direction])

    from sim import environment

    wind = environment.Wind()
    radius = 3
    kernel = fire_spread.build_kernel(radius, config.MU, direction)

    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx == 0 and dy == 0:
                continue  # see the note in the test above: the centre is never a neighbour
            weight = formulas.distance_rate((0, 0), (dx, dy), radius)
            if weight <= 0:
                assert kernel[dx + radius, dy + radius] == 0
                continue
            # apply_wind() takes the cell and the neighbour, here (0, 0) and the offset itself
            expected_weight = wind.apply_wind(weight, (0, 0), (dx, dy))
            entry = kernel[dx + radius, dy + radius]
            if expected_weight >= 1.0:
                assert entry == fire_spread.NEG_INF
            else:
                assert entry == pytest.approx(math.log1p(-expected_weight), abs=1e-15)


# the offset form of is_on_wind_direction() has to agree with the original, which compares positions
@pytest.mark.parametrize("direction", WIND_DIRECTIONS)
def test_on_wind_matches_is_on_wind_direction(direction, sim_config):
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=[direction])

    from sim import environment

    wind = environment.Wind()
    cell = (10, 10)
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            neighbour = (cell[0] + dx, cell[1] + dy)
            assert fire_spread.on_wind(direction, dx, dy) == wind.is_on_wind_direction(cell, neighbour), \
                f"{direction} disagrees at offset {(dx, dy)}"


def test_unknown_wind_direction_is_rejected():
    with pytest.raises(ValueError, match="unknown wind direction"):
        fire_spread.on_wind("sideways", 1, 0)


# the direction names are matched case insensitively, because config.py shipped them in lower case for
# years and the sweeps under experiments/ still pass them that way
def test_direction_names_are_case_insensitive():
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            assert fire_spread.on_wind("south", dx, dy) == fire_spread.on_wind("SOUTH", dx, dy)


# A cardinal wind favours the three cells of its column; a diagonal one favours the two cells of its
# diagonal, because the third lies at distance 4.24 and falls outside the spread radius of 3.
#
# That asymmetry is deliberate -- see the MU entry in config.py -- and this test exists to make removing
# it a decision rather than an accident. Widening the downwind set into a cone would change cardinal
# spread too, and every calibrated number in config.py was measured against the column.
@pytest.mark.parametrize("direction, expected", (
    ("SOUTH", {(0, 1), (0, 2), (0, 3)}),
    ("NORTH", {(0, -1), (0, -2), (0, -3)}),
    ("EAST", {(-1, 0), (-2, 0), (-3, 0)}),
    ("WEST", {(1, 0), (2, 0), (3, 0)}),
    ("SOUTH_EAST", {(-1, 1), (-2, 2)}),
    ("NORTH_EAST", {(-1, -1), (-2, -2)}),
    ("SOUTH_WEST", {(1, 1), (2, 2)}),
    ("NORTH_WEST", {(1, -1), (2, -2)}),
))
def test_downwind_offsets_are_a_single_ray(direction, expected):
    radius, mu = 3, 0.5
    # the offsets the wind actually lifts, which is on_wind() narrowed by the radius: the third cell of a
    # diagonal ray sits at distance 4.24 and is dropped, so a diagonal lifts two cells where a cardinal
    # lifts three. That is the asymmetry, and it belongs to cell_weight() rather than to on_wind()
    boosted = {
        (dx, dy)
        for dx in range(-radius, radius + 1)
        for dy in range(-radius, radius + 1)
        if fire_spread.on_wind(direction, dx, dy)
        and fire_spread.cell_weight(dx, dy, radius, mu) > 0
    }
    assert boosted == expected

    # and every one of them is at least as strong as it would be with no wind, which is the other half of
    # what "downwind" means. The nearest cardinal cell is the equality: its weight is already 1
    for dx, dy in boosted:
        assert (fire_spread.cell_weight(dx, dy, radius, mu, direction)
                >= fire_spread.cell_weight(dx, dy, radius, mu))


# the corner an on-wind diagonal ray runs through lies at distance 4.24, beyond the spread radius, so it
# contributes nothing at all -- the wind must not lift it from nothing to MU. The Moore window offers that
# cell, distance_rate() answers 0 for it, and a bias applied before the range check turns a neighbour four
# cells away into a coin toss. Both implementations are checked, because it was only ever wrong in one.
def test_an_out_of_range_corner_is_never_lifted_by_the_wind(sim_config):
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=["SOUTH_EAST"])

    from sim import environment

    assert fire_spread.on_wind("SOUTH_EAST", -3, 3), "the ray does run through the corner"
    assert fire_spread.cell_weight(-3, 3, 3, config.MU, "SOUTH_EAST") == 0.0
    assert fire_spread.build_kernel(3, config.MU, "SOUTH_EAST")[0, 6] == 0.0

    wind = environment.Wind()
    weight = formulas.distance_rate((5, 5), (2, 8), 3)
    assert weight == 0
    assert wind.apply_wind(weight, (5, 5), (2, 8)) == 0


# every offset that is not on the ray is suppressed by the same MU, crosswind and the flanking diagonals
# included. The comments used to say "upwind", which is only a quarter of the truth.
def test_everything_off_the_ray_is_suppressed():
    radius, mu = 3, 0.5
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            plain = fire_spread.cell_weight(dx, dy, radius, mu)
            windy = fire_spread.cell_weight(dx, dy, radius, mu, "SOUTH")
            if plain == 0.0:
                continue
            if fire_spread.on_wind("SOUTH", dx, dy):
                assert windy == pytest.approx(plain + mu * (1 - plain))
            else:
                assert windy == pytest.approx(plain * (1 - mu)), f"offset {(dx, dy)}"


# ---------------------------------------------------------------------------
# equivalence with the per cell implementation
# ---------------------------------------------------------------------------


def test_matches_per_cell_without_wind(make_model):
    worst, burning = worst_disagreement(make_model, ACTIVATE_WIND=False,
                                        HEIGHT=30, WIDTH=30, FIRE_START_POSITION=(15, 15),
                                        FIRE_START_STEP=0, ACTIVATE_FIREFIGHTING=False)
    assert burning > 0, "the comparison is vacuous with nothing alight"
    assert worst < TOLERANCE


@pytest.mark.parametrize("direction", WIND_DIRECTIONS)
def test_matches_per_cell_with_fixed_wind(direction, make_model):
    worst, burning = worst_disagreement(make_model, ACTIVATE_WIND=True,
                                        WIND_DIRECTION=[direction],
                                        HEIGHT=30, WIDTH=30, FIRE_START_POSITION=(15, 15),
                                        FIRE_START_STEP=0, ACTIVATE_FIREFIGHTING=False)
    assert burning > 0
    assert worst < TOLERANCE


# the grid is not a torus, so a fire in the corner must not wrap round to the far side
@pytest.mark.parametrize("corner", ((0, 0), (0, 29), (29, 0), (29, 29)))
def test_matches_per_cell_at_the_edges(corner, make_model):
    worst, burning = worst_disagreement(make_model, ACTIVATE_WIND=False,
                                        HEIGHT=30, WIDTH=30, FIRE_START_POSITION=corner,
                                        FIRE_START_STEP=0, ACTIVATE_FIREFIGHTING=False)
    assert burning > 0
    assert worst < TOLERANCE


# with a density below 1 the grid has holes in it, and cells with no Fire agent must contribute
# nothing, exactly as they are absent from the per cell product
def test_matches_per_cell_with_sparse_vegetation(make_model):
    worst, burning = worst_disagreement(make_model, ACTIVATE_WIND=False, DENSITY_PROB=0.6,
                                        HEIGHT=30, WIDTH=30, FIRE_START_POSITION=(15, 15),
                                        FIRE_START_STEP=0, ACTIVATE_FIREFIGHTING=False)
    assert burning > 0
    assert worst < TOLERANCE


# HEIGHT and WIDTH are equal in every shipped configuration, which would hide an axis mix up. The
# grid is MultiGrid(HEIGHT, WIDTH), so a position's first coordinate runs over HEIGHT.
def test_matches_per_cell_on_a_non_square_grid(make_model):
    worst, burning = worst_disagreement(make_model, ACTIVATE_WIND=False,
                                        HEIGHT=17, WIDTH=29, FIRE_START_POSITION=(8, 14),
                                        FIRE_START_STEP=0, ACTIVATE_FIREFIGHTING=False)
    assert burning > 0
    assert worst < TOLERANCE


def test_field_is_shaped_like_the_grid(make_model):
    model = make_model(HEIGHT=17, WIDTH=29, ACTIVATE_FIREFIGHTING=False)
    assert model.fire_spread.probability_field(model.burning).shape == (17, 29)


# ---------------------------------------------------------------------------
# degenerate cases
# ---------------------------------------------------------------------------


def test_nothing_burning_gives_no_probability(make_model):
    model = make_model(HEIGHT=20, WIDTH=20, FIRE_START_STEP=10_000, ACTIVATE_FIREFIGHTING=False)
    field = model.fire_spread.probability_field(numpy.zeros((20, 20), dtype=bool))
    assert numpy.array_equal(field, numpy.zeros((20, 20)))


def test_field_never_produces_nan_or_inf(make_model):
    model = make_model(HEIGHT=25, WIDTH=25, FIRE_START_POSITION=(12, 12), FIRE_START_STEP=0,
                       ACTIVATE_FIREFIGHTING=False)
    burn_for_a_while(model)
    field = model.fire_spread.probability_field(model.burning)
    assert numpy.isfinite(field).all()
    assert ((field >= 0.0) & (field <= 1.0)).all()


# a burning orthogonal neighbour sits at distance 1, where the weight is exactly 1, so the cell is
# certain to ignite. That is the case NEG_INF stands in for, and it has to come out as exactly 1.0.
def test_orthogonal_neighbour_forces_ignition(make_model):
    model = make_model(HEIGHT=20, WIDTH=20, ACTIVATE_WIND=False, ACTIVATE_FIREFIGHTING=False)
    burning = numpy.zeros((20, 20), dtype=bool)
    burning[10, 10] = True

    field = model.fire_spread.probability_field(burning)
    for neighbour in ((9, 10), (11, 10), (10, 9), (10, 11)):
        assert field[neighbour] == 1.0, f"{neighbour} should be certain to ignite"
    # a cell beyond the radius is untouched
    assert field[10, 14] == 0.0


# the kernel is built for one radius, so a Fire agent that disagrees has to be caught rather than
# silently given the wrong physics
def test_mismatched_radius_is_rejected(make_model):
    model = make_model(HEIGHT=12, WIDTH=12, ACTIVATE_FIREFIGHTING=False)
    model.fire_list[0].radius = 5
    with pytest.raises(ValueError, match="spread kernel was built for"):
        model.fire_spread.assert_matches(model.fire_list)
