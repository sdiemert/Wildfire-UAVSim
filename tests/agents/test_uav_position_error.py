"""Tests for the positioning error extension: a UAV that does not know exactly where it is.

With ACTIVATE_POSITION_ERROR on, a UAV's *measured* position is its true cell displaced by a fixed bias it
was created with plus a jitter it redraws every step, both uniform integers per axis. The measurement is
what its policy plans from, what the team mates that can see it are told, and what the managing system is
shown. The mesa grid position is untouched ground truth, and the whole section below headed "ground truth is
untouched" exists to keep it that way: movement, collisions, fuel, the home base and MR1/MR2 must all give
the same answers whatever the receivers are doing, or a run with the extension on could not be compared
with one without it.

What a UAV *sees* -- the burning cells, the base footprint, the out buildings -- stays in true grid
coordinates. That is not a shortcut: a policy steers by the difference between where it thinks it is and
where the target is, so displacing both by the same offset would cancel the error out exactly and the whole
extension would be a no-op. There is a test for it, because it is the kind of thing a later refactor
"tidies up".

Several tests set position_bias directly on an agent rather than hunting for a seed that produces the
offset they want, which keeps them readable and independent of the generator. Where a real draw is under
test, the fixture seeds SYSTEM_RANDOM instead.

The tests that run the same script with the extension on and off keep the fire out of the run, and have to.
The offsets are drawn from SYSTEM_RANDOM, so switching the extension on moves every later draw along and a
fire would spread differently for that reason alone -- which says nothing about whether the extension
touched ground truth. Where a burning cell is needed, the test lights it itself and pins the answer
directly.

The per step jitter is not a draw from SYSTEM_RANDOM: formulas.position_noise() works it out from the UAV
and the step number, so a fix is one fixed value that can be asked for at any time, in any order, without
moving the run along. Several tests below lean on that, and one of them pins it, because the alternative --
a lazily drawn fix -- makes the status panel and any test that peeks at a single UAV into things that
silently change the simulation they are looking at.

Direction reminder, from the movement vectors in UAV.move():
    ACTION_RIGHT  x + 1        ACTION_LEFT  x - 1
    ACTION_UP     y + 1        ACTION_DOWN  y - 1
"""

# python libraries

import random

import pytest

# own python modules

import config

from sim import formulas

from config import ACTION_RIGHT, ACTION_STAY

from sim.policy import Action, Policy


# --- helpers ----------------------------------------------------------------


class ScriptedPolicy(Policy):
    """Gives the UAVs the actions listed by their place in the team, so a test can fly a fleet on rails.

    Anything left out of the script holds position. Flying on rails is what separates "the belief moved"
    from "the aircraft moved": the same script under the same seed has to produce the same trajectory
    whatever the receivers report, which is most of what the tests below check.
    """

    name = "scripted"

    def __init__(self, actions=None):
        self.actions = dict(actions or {})

    def select_actions(self, observations):
        return [self.actions.get(index, Action(ACTION_STAY, 0))
                for index, _ in enumerate(observations)]


@pytest.fixture
def fleet(make_model):
    """A model on a 15x15 grid with the positioning error extension on and the fire kept out of the way.

    The grid is deliberately larger than the 9x9 the make_model fixture defaults to, so that a UAV placed in
    the middle has room to be several cells wrong in any direction without the clamp taking a hand. The
    clamp has a section of its own.
    """

    def _make(count=1, policy=None, **overrides):
        settings = {"WIDTH": 15, "HEIGHT": 15, "NUM_AGENTS": count, "ACTIVATE_FIREFIGHTING": False,
                    "FIRE_START_STEP": 10_000, "ACTIVATE_POSITION_ERROR": True,
                    "UAV_POSITION_BIAS_MAX": 2, "UAV_POSITION_NOISE_MAX": 1}
        settings.update(overrides)
        return make_model(policy=policy, **settings)

    return _make


def place(model, positions):
    """Puts UAV i of the team on positions[i]."""
    for uav, position in zip(model.uavs, positions):
        model.grid.move_agent(uav, position)


def bias(model, offsets):
    """Gives UAV i of the team the fixed bias offsets[i], in place of the one it drew."""
    for uav, offset in zip(model.uavs, offsets):
        uav.position_bias = offset
        uav._position_offset = (None, (0, 0))   # so the next fix is worked out from the new bias


def offsets_over(model, steps):
    """The offset between belief and truth for the single UAV of a model, once per step, before each step."""
    uav = model.uavs[0]
    seen = []
    for _ in range(steps):
        measured = uav.measured_pos()
        seen.append((measured[0] - uav.pos[0], measured[1] - uav.pos[1]))
        model.step()
    return seen


# --- the extension switched off ---------------------------------------------


def test_a_uav_reports_its_true_cell_when_the_extension_is_off(fleet):
    model = fleet(ACTIVATE_POSITION_ERROR=False, UAV_POSITION_BIAS_MAX=5, UAV_POSITION_NOISE_MAX=5)
    uav = model.uavs[0]

    assert uav.position_bias == (0, 0)
    assert uav.measured_pos() == uav.pos
    assert uav.observe().pos == uav.pos


def test_no_offset_is_drawn_when_the_extension_is_off(monkeypatch, sim_config, seed_rng):
    """The property every seeded result in the project rests on: with the flag off, nothing is drawn.

    An offset of (0, 0) would not be enough. A draw taken and thrown away still moves the generator on, and
    every existing run would come out differently the day the extension was merged.
    """
    seed_rng(0)
    sim_config(ACTIVATE_POSITION_ERROR=False)

    def refuse(*args, **kwargs):
        raise AssertionError("an offset was drawn with the positioning error extension switched off")

    monkeypatch.setattr(config.SYSTEM_RANDOM, "randint", refuse)

    assert formulas.draw_position_offset(5) == (0, 0)


def test_a_zero_magnitude_takes_no_draw_either(monkeypatch, sim_config, seed_rng):
    """Same reasoning for the control arm of a sweep: on, but with nothing to do."""
    seed_rng(0)
    sim_config(ACTIVATE_POSITION_ERROR=True)

    def refuse(*args, **kwargs):
        raise AssertionError("an offset was drawn for a magnitude of zero")

    monkeypatch.setattr(config.SYSTEM_RANDOM, "randint", refuse)

    assert formulas.draw_position_offset(0) == (0, 0)


def test_a_run_with_the_flag_off_is_the_run_it_always_was(fleet, sim_config):
    """A flag-off run with large magnitudes set must match one that has nothing to draw at all."""
    sim_config(SYSTEM_RANDOM=random.Random(7))
    loud = fleet(count=3, DENSITY_PROB=0.8, FIRE_START_STEP=0, ACTIVATE_POSITION_ERROR=False,
                 UAV_POSITION_BIAS_MAX=4, UAV_POSITION_NOISE_MAX=3)
    for _ in range(12):
        loud.step()

    sim_config(SYSTEM_RANDOM=random.Random(7))
    quiet = fleet(count=3, DENSITY_PROB=0.8, FIRE_START_STEP=0, ACTIVATE_POSITION_ERROR=False,
                  UAV_POSITION_BIAS_MAX=0, UAV_POSITION_NOISE_MAX=0)
    for _ in range(12):
        quiet.step()

    assert [uav.pos for uav in loud.uavs] == [uav.pos for uav in quiet.uavs]
    assert [fire.fuel for fire in loud.fire_list] == [fire.fuel for fire in quiet.fire_list]
    assert loud.MR2_VALUE == quiet.MR2_VALUE


# --- the fixed bias ---------------------------------------------------------


def test_the_bias_is_drawn_once_and_held_for_the_whole_run(fleet, seed_rng):
    """A receiver that was never calibrated is wrong in the same way on every step of the run.

    Parked in the middle of the grid, because a UAV that wanders onto an edge has the offset it reports
    trimmed by the clamp, which would look from the outside like a bias that had changed.
    """
    seed_rng(3)
    model = fleet(policy=ScriptedPolicy(), UAV_POSITION_BIAS_MAX=3, UAV_POSITION_NOISE_MAX=0)
    place(model, [(7, 7)])
    uav = model.uavs[0]
    drawn = uav.position_bias

    assert offsets_over(model, steps=6) == [drawn] * 6
    assert uav.position_bias == drawn


def test_every_uav_draws_a_bias_of_its_own(fleet, seed_rng):
    """The spread of a fleet of receivers of varying quality, not one error the whole team shares."""
    seed_rng(11)
    model = fleet(count=8, UAV_POSITION_BIAS_MAX=2)
    biases = [uav.position_bias for uav in model.uavs]

    assert all(-2 <= axis <= 2 for offset in biases for axis in offset)
    assert len(set(biases)) > 1


def test_a_bias_magnitude_of_zero_leaves_only_the_noise(fleet, seed_rng):
    seed_rng(4)
    model = fleet(UAV_POSITION_BIAS_MAX=0, UAV_POSITION_NOISE_MAX=2)

    assert model.uavs[0].position_bias == (0, 0)
    assert len(set(offsets_over(model, steps=20))) > 1


# --- the per step jitter ----------------------------------------------------


def test_the_jitter_is_redrawn_every_step(fleet, uav_speed):
    """The fleet is grounded, so anything that moves is the belief rather than the aircraft."""
    uav_speed(0)
    model = fleet(UAV_POSITION_BIAS_MAX=0, UAV_POSITION_NOISE_MAX=2)
    uav = model.uavs[0]
    started_at = uav.pos

    seen = offsets_over(model, steps=20)

    assert uav.pos == started_at
    assert len(set(seen)) > 1


def test_the_same_step_yields_the_same_fix_however_often_it_is_asked_for(fleet):
    """The invariant the per step cache exists for.

    WildFireModel.observations() asks every UAV what it can see for the policy, and
    ModelSensor.uav_report() asks again for the managing system. Two different answers within one step
    would be an artefact of this code rather than an error the UAV could have made.
    """
    model = fleet(UAV_POSITION_NOISE_MAX=3)
    uav = model.uavs[0]

    for _ in range(6):
        fix = uav.measured_pos()
        assert uav.observe().pos == fix
        assert uav.observe().pos == fix
        assert uav.measured_pos() == fix
        model.step()


def test_asking_a_uav_where_it_thinks_it_is_takes_nothing_from_system_random(monkeypatch, fleet):
    """The property the status panel rests on, and the reason the jitter is not a draw.

    The panel renders between steps and a test may want one UAV's fix on its own. If the jitter came from
    SYSTEM_RANDOM, either of those would move every later draw along, and a simulation watched in a browser
    would come out differently from the same one in headless.py -- a difference that would be found by
    somebody comparing results rather than by a test.
    """
    model = fleet(count=3, UAV_POSITION_NOISE_MAX=2)

    def refuse(*args, **kwargs):
        raise AssertionError("working out a fix drew from the shared generator")

    for name in ("random", "randint", "choice", "randrange", "sample", "shuffle", "getrandbits"):
        monkeypatch.setattr(config.SYSTEM_RANDOM, name, refuse)

    for uav in model.uavs:
        assert uav.measured_pos() is not None
        assert uav.observe().pos is not None


def test_a_fix_is_the_same_answer_whenever_it_is_asked_for(fleet):
    """Asking out of turn, or about one UAV and not the others, gives the same fixes either way."""
    def fixes(peeking):
        model = fleet(count=3, policy=ScriptedPolicy(), UAV_POSITION_NOISE_MAX=2,
                      SYSTEM_RANDOM=random.Random(5))
        place(model, [(7, 7), (9, 9), (11, 4)])
        seen = []
        for _ in range(8):
            if peeking:
                # the awkward pattern: one UAV, repeatedly, out of team order, mid run
                model.uavs[2].measured_pos()
                model.uavs[2].measured_pos()
                model.uavs[0].measured_pos()
            model.step()
            seen.append([uav.measured_pos() for uav in model.uavs])
        return seen

    assert fixes(peeking=True) == fixes(peeking=False)


def test_a_noise_magnitude_of_zero_leaves_only_the_bias(fleet):
    # grounded and parked well away from the edges, so the clamp cannot trim the offset being measured
    model = fleet(policy=ScriptedPolicy(), UAV_POSITION_NOISE_MAX=0)
    bias(model, [(2, -1)])
    place(model, [(7, 7)])

    assert offsets_over(model, steps=5) == [(2, -1)] * 5


def test_the_offset_never_exceeds_the_bias_plus_the_noise(fleet, seed_rng, uav_speed):
    """On a grid big enough that the clamp cannot be what is keeping the numbers down."""
    seed_rng(21)
    uav_speed(0)
    model = fleet(WIDTH=41, HEIGHT=41, UAV_POSITION_BIAS_MAX=2, UAV_POSITION_NOISE_MAX=3)

    seen = offsets_over(model, steps=30)

    assert all(abs(axis) <= 5 for offset in seen for axis in offset)
    assert any(abs(axis) > 2 for offset in seen for axis in offset)   # the jitter really is in there


# --- clamping ---------------------------------------------------------------


def test_a_measured_position_is_always_a_cell_that_exists(fleet, seed_rng, uav_speed):
    seed_rng(5)
    uav_speed(0)
    model = fleet(WIDTH=9, HEIGHT=9, UAV_POSITION_BIAS_MAX=20, UAV_POSITION_NOISE_MAX=20)
    place(model, [(0, 0)])
    uav = model.uavs[0]

    for _ in range(30):
        assert not model.grid.out_of_bounds(uav.measured_pos())
        assert not model.grid.out_of_bounds(uav.observe().pos)
        model.step()


def test_a_large_error_is_clamped_to_the_edge_rather_than_wrapped(fleet, seed_rng, uav_speed):
    """Which also keeps the test above from passing on an error too small to reach an edge."""
    seed_rng(5)
    uav_speed(0)
    model = fleet(WIDTH=9, HEIGHT=9, UAV_POSITION_BIAS_MAX=20, UAV_POSITION_NOISE_MAX=0)
    place(model, [(4, 4)])
    uav = model.uavs[0]

    # the bias is far larger than the grid, so whichever way it points the fix lands in a corner
    assert uav.measured_pos() in [(0, 0), (0, 8), (8, 0), (8, 8)]


# --- ground truth is untouched ----------------------------------------------


def test_a_positioning_error_never_moves_a_uav(fleet):
    """The same script has to fly the same trajectory whatever the receiver says."""
    def trajectory(**overrides):
        model = fleet(policy=ScriptedPolicy({0: Action(ACTION_RIGHT, 2)}),
                      UAV_POSITION_BIAS_MAX=4, UAV_POSITION_NOISE_MAX=2, **overrides)
        place(model, [(3, 7)])
        flown = []
        for _ in range(4):
            model.step()
            flown.append(model.uavs[0].pos)
        return flown

    assert trajectory() == trajectory(ACTIVATE_POSITION_ERROR=False)


def test_collisions_are_settled_from_where_the_uavs_really_are(fleet):
    """Two UAVs flown onto one cell have collided, however far apart they believe they are."""
    model = fleet(count=2, policy=ScriptedPolicy({0: Action(ACTION_RIGHT, 1)}),
                  UAV_POSITION_BIAS_MAX=4, UAV_COLLISION_DAMAGE_MEAN=1.0, UAV_HP=3)
    bias(model, [(4, 4), (-4, -4)])
    place(model, [(5, 7), (6, 7)])

    model.step()

    assert model.uavs[0].pos == model.uavs[1].pos == (6, 7)
    assert model.collisions == 1
    assert [uav.hp for uav in model.uavs] == [2, 2]


def test_mr2_is_scored_from_the_true_positions(fleet):
    """MR2 counts the pairs that really were too close, not the pairs the team thought it had."""
    def scored(**overrides):
        model = fleet(count=3, policy=ScriptedPolicy(), UAV_POSITION_BIAS_MAX=4,
                      UAV_POSITION_NOISE_MAX=2, **overrides)
        place(model, [(5, 7), (6, 7), (11, 2)])
        for _ in range(5):
            model.step()
        return model.MR2_VALUE

    assert scored() == scored(ACTIVATE_POSITION_ERROR=False)


def test_fuel_is_charged_for_the_cells_really_covered(fleet):
    """Fuel is physics: a UAV that believes it is parked still pays for the ground it covers."""
    def burned(**overrides):
        model = fleet(policy=ScriptedPolicy({0: Action(ACTION_RIGHT, 3)}), ACTIVATE_FUEL=True,
                      UAV_POSITION_BIAS_MAX=4, UAV_POSITION_NOISE_MAX=2, **overrides)
        place(model, [(2, 7)])
        for _ in range(3):
            model.step()
        return round(model.uavs[0].fuel, 6)

    assert burned() == burned(ACTIVATE_POSITION_ERROR=False)


def test_the_base_serves_a_uav_that_believes_it_is_somewhere_else(fleet):
    """The ground crew can see the aircraft on the pad, whatever the aircraft thinks.

    This is the failure mode the extension is most interesting for, seen from the base's side: the UAV's
    own at_base() is False, so a policy reading it would fly off looking for a base it is standing on, but
    the refill itself is settled from the grid and goes ahead.
    """
    model = fleet(policy=ScriptedPolicy(), ACTIVATE_FIREFIGHTING=True, ACTIVATE_FUEL=True,
                  BASE_POSITION=(3, 3), BASE_SIZE=(1, 1), BASE_REFILL_STEPS=1, BASE_REFUEL_STEPS=1,
                  UAV_POSITION_NOISE_MAX=0)
    bias(model, [(5, 5)])
    place(model, [(3, 3)])
    uav = model.uavs[0]
    uav.water = 0
    uav.fuel = 10.0

    observation = uav.observe()
    assert observation.pos == (8, 8)
    assert not observation.at_base()          # the UAV does not believe it is on the base
    assert observation.base_cells == [(3, 3)]  # but it is told where the base really is

    model.step()
    model.step()

    assert model.refills == 1
    assert uav.water == config.UAV_WATER_CAPACITY
    assert uav.fuel == float(config.UAV_FUEL)


def test_the_cells_a_uav_flies_over_are_the_ones_it_really_flies_over(fleet):
    """Water lands under the aircraft, not under where it thinks it is."""
    model = fleet(policy=ScriptedPolicy(), ACTIVATE_FIREFIGHTING=True, DENSITY_PROB=1.0,
                  WATER_DROP_RADIUS=0, WATER_EXTINGUISH_PROB_CENTRE=1.0, UAV_POSITION_NOISE_MAX=0)
    bias(model, [(4, 4)])
    place(model, [(7, 7)])
    uav = model.uavs[0]

    model.fire_agent_at((7, 7)).burning = True
    assert uav.dump_water() == 1
    assert not model.fire_agent_at((7, 7)).is_burning()


# --- what the neighbours are told -------------------------------------------


def test_a_uav_is_told_the_position_its_neighbour_measured(fleet):
    """There is no UAV to UAV link in the project, so this is what "B reported its position" means."""
    model = fleet(count=2, UAV_POSITION_NOISE_MAX=0)
    bias(model, [(0, 0), (2, -1)])
    place(model, [(7, 7), (8, 7)])
    first, second = model.uavs

    assert first.observe().uav_positions == [second.measured_pos()]
    assert first.observe().uav_positions == [(10, 6)]
    assert first.observe().uav_positions != [second.pos]


def test_a_uav_does_not_apply_its_own_error_to_its_neighbours(fleet):
    """Exactly one error is applied per reported UAV: the one belonging to the UAV being reported."""
    model = fleet(count=2, UAV_POSITION_NOISE_MAX=0)
    bias(model, [(3, 3), (0, 0)])
    place(model, [(7, 7), (8, 7)])
    first, second = model.uavs

    observation = first.observe()
    assert observation.pos == (10, 10)              # its own fix is displaced
    assert observation.uav_positions == [(8, 7)]    # its well calibrated neighbour is reported truthfully


def test_a_neighbour_is_reported_once_however_wrong_its_fix_is(fleet):
    """Two UAVs can measure the same cell, and the count of what is in view still has to be right."""
    model = fleet(count=3, UAV_POSITION_NOISE_MAX=0)
    bias(model, [(0, 0), (1, 0), (0, 0)])
    place(model, [(7, 7), (8, 7), (9, 7)])
    first = model.uavs[0]

    # UAV 1 measures itself onto the cell UAV 2 is really on, so the two reports coincide
    assert model.uavs[1].measured_pos() == model.uavs[2].pos == (9, 7)
    assert first.observe().uav_positions == [(9, 7), (9, 7)]


def test_a_uav_reports_no_position_once_it_is_destroyed(fleet):
    model = fleet()
    uav = model.uavs[0]
    model.destroy_uav(uav)

    assert uav.pos is None
    assert uav.measured_pos() is None


# --- what a UAV sees stays true ---------------------------------------------


def test_the_cells_a_uav_sees_are_in_true_grid_coordinates(fleet):
    """The error belongs to the receiver, not the camera -- and the extension needs it that way.

    A policy steers by the difference between Observation.pos and its target. Displacing the observed cells
    by the same offset as the position would cancel that difference exactly, and a run with the extension on
    would fly identically to one without it.
    """
    def seen(**overrides):
        model = fleet(DENSITY_PROB=1.0, UAV_POSITION_NOISE_MAX=0, **overrides)
        bias(model, [(3, -2)])
        place(model, [(7, 7)])
        return sorted(position for position, _ in model.uavs[0].observe().cells)

    with_error = seen()
    assert with_error == seen(ACTIVATE_POSITION_ERROR=False)
    # and the window really is centred on the true cell (7, 7) rather than on the measured (10, 5): with a
    # radius of 4 that is x and y over 3..11, where a window around the measurement would reach 14
    assert (7, 7) in with_error
    assert min(position[0] for position in with_error) == 3
    assert max(position[0] for position in with_error) == 11
    assert max(position[1] for position in with_error) == 11


def test_the_base_and_the_out_buildings_are_reported_where_they_really_are(fleet):
    model = fleet(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(6, 6), BASE_SIZE=(2, 2),
                  NUM_OUT_BUILDINGS=3, UAV_POSITION_NOISE_MAX=0)
    bias(model, [(2, 2)])
    place(model, [(7, 7)])
    observation = model.uavs[0].observe()

    assert observation.base_pos == model.base.pos
    assert sorted(observation.base_cells) == sorted(model.base.cells)
    for position in observation.building_positions:
        assert model.grid.get_cell_list_contents([position])


def test_the_flat_state_the_model_scores_is_unaffected(fleet):
    """MR1 and state() are built from the observed cells, so the error must not reach them.

    Pinned against the fire the test lights itself rather than against the same run with the extension off.
    Comparing the two would not be sound: the offsets are drawn from SYSTEM_RANDOM, so switching the
    extension on moves every later draw along, and the fire would spread differently for that reason alone.
    That is why every comparison across the flag in this file keeps the fire out of the run.
    """
    model = fleet(DENSITY_PROB=1.0, UAV_POSITION_NOISE_MAX=0)
    bias(model, [(3, -2)])
    place(model, [(7, 7)])
    model.fire_agent_at((6, 8)).burning = True

    observation = model.uavs[0].observe()
    assert observation.burning_positions() == [(6, 8)]

    # state() pads the same flat list out to N_OBSERVATIONS, so what MR1 counts is the ground the UAV
    # really overflew and not the ground it believes it did
    flat = observation.flat_states()
    assert model.state()[0][:len(flat)] == flat
    assert sum(model.state()[0]) == 1
