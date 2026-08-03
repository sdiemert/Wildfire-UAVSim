"""Tests for UAV collisions: what happens when two of them end a step on the same cell.

Two UAVs sharing a cell have collided, and each of them rolls for damage: a whole health point or nothing
at all, averaging out at UAV_COLLISION_DAMAGE_MEAN. A UAV whose health points run out is destroyed and
takes no further part in the run. The home base is the one place they can share, because that is where the
whole team starts and refills.

Most of these pin the mean at 1.0, which makes the damage certain and the tests deterministic. The rolls
themselves have a section of their own.

SECURITY_DISTANCE takes no part in any of this: it is the heuristic MR2 scores collision risk with, and
the last section here pins that the two are independent.

Direction reminder, from the movement vectors in UAV.move():
    ACTION_RIGHT  x + 1        ACTION_LEFT  x - 1
    ACTION_UP     y + 1        ACTION_DOWN  y - 1
"""

# python libraries

import pytest

# own python modules

import config

from config import ACTION_LEFT, ACTION_RIGHT, ACTION_STAY

from sim.policy import Action, Policy


# --- helpers ----------------------------------------------------------------


class ScriptedPolicy(Policy):
    """Gives the UAVs the actions listed by their place in the team, so a test can fly a fleet into itself.

    Anything left out of the script holds position, which keeps a UAV where the test put it. The places
    are those of the UAVs still flying, so a script written for a full team is only meaningful until one
    of them is destroyed; the tests that get that far leave the script empty.
    """

    name = "scripted"

    def __init__(self, actions=None):
        self.actions = dict(actions or {})

    def select_actions(self, observations):
        return [self.actions.get(index, Action(ACTION_STAY, 0))
                for index, _ in enumerate(observations)]


@pytest.fixture
def fleet(make_model):
    """A model flying several UAVs on a 9x9 grid, with the fire kept out of the way.

    The firefighting extension is off by default, so there is no base to be exempt from collisions; the
    tests that care about the base switch it back on. The damage mean is pinned at 1.0, so that a collision
    certainly costs a health point and the outcome does not depend on a roll.
    """

    def _make(count=2, **overrides):
        settings = {"NUM_AGENTS": count, "ACTIVATE_FIREFIGHTING": False,
                    "FIRE_START_STEP": 10_000, "UAV_SPEED": 5, "UAV_HP": 3,
                    "UAV_COLLISION_DAMAGE_MEAN": 1.0}
        settings.update(overrides)
        return make_model(**settings)

    return _make


def place(model, positions):
    """Puts UAV i of the team on positions[i]."""
    for uav, position in zip(model.uavs, positions):
        model.grid.move_agent(uav, position)


# --- health points ----------------------------------------------------------


def test_a_uav_starts_with_the_configured_health_points(fleet):
    model = fleet(count=1, UAV_HP=7)
    assert model.uavs[0].hp == 7
    assert model.uavs[0].is_alive()


def test_damage_never_takes_health_points_below_zero(fleet):
    model = fleet(count=1, UAV_HP=2)
    drone = model.uavs[0]

    assert drone.take_damage(5) == 2
    assert drone.hp == 0
    assert not drone.is_alive()
    # a UAV that is already down cannot be hit again
    assert drone.take_damage(1) == 0


# --- colliding --------------------------------------------------------------


def test_two_uavs_left_on_the_same_cell_both_lose_health(fleet):
    model = fleet(count=2)
    place(model, [(2, 4), (6, 4)])

    model.resolve_collisions()  # they are apart, so nothing happens
    assert [uav.hp for uav in model.uavs] == [3, 3]

    place(model, [(4, 4), (4, 4)])
    model.resolve_collisions()

    assert [uav.hp for uav in model.uavs] == [2, 2]
    assert model.collisions == 1


def test_a_uav_that_flies_into_another_one_collides_with_it(fleet):
    # UAV 0 flies right into UAV 1, which holds position
    model = fleet(count=2, policy=ScriptedPolicy({0: Action(ACTION_RIGHT, 3)}))
    place(model, [(2, 4), (5, 4)])

    model.step()

    assert model.uavs[0].pos == (5, 4)
    assert [uav.hp for uav in model.uavs] == [2, 2]
    assert model.collisions == 1


def test_a_whole_pile_of_uavs_on_one_cell_is_one_collision_for_each_of_them(fleet):
    model = fleet(count=3)
    place(model, [(4, 4), (4, 4), (4, 4)])

    model.resolve_collisions()

    # each of them pays once for the step, however many others it shared the cell with
    assert [uav.hp for uav in model.uavs] == [2, 2, 2]
    assert model.collisions == 1


def test_uavs_left_stacked_keep_colliding_every_step(fleet):
    model = fleet(count=2, UAV_HP=5, policy=ScriptedPolicy({}))  # nobody moves
    place(model, [(4, 4), (4, 4)])

    model.step()
    assert [uav.hp for uav in model.uavs] == [4, 4]
    model.step()
    assert [uav.hp for uav in model.uavs] == [3, 3]
    assert model.collisions == 2


def test_a_collision_never_costs_more_than_one_health_point(fleet):
    # however the mean is set, one collision is one health point at most
    model = fleet(count=2, UAV_HP=10, UAV_COLLISION_DAMAGE_MEAN=4.0)
    place(model, [(4, 4), (4, 4)])

    model.resolve_collisions()

    assert [uav.hp for uav in model.uavs] == [9, 9]


def test_uavs_that_only_pass_close_to_each_other_do_not_collide(fleet):
    model = fleet(count=2)
    place(model, [(4, 4), (4, 5)])

    model.resolve_collisions()

    assert [uav.hp for uav in model.uavs] == [3, 3]
    assert model.collisions == 0


# --- rolling the damage -----------------------------------------------------


def test_the_default_mean_always_costs_a_full_health_point(seed_rng, sim_config):
    sim_config(UAV_COLLISION_DAMAGE_MEAN=1.0)
    seed_rng(0)
    assert [config.roll_collision_damage() for _ in range(200)] == [1] * 200


def test_a_mean_of_zero_never_costs_anything(seed_rng, sim_config):
    sim_config(UAV_COLLISION_DAMAGE_MEAN=0.0)
    seed_rng(0)
    assert [config.roll_collision_damage() for _ in range(200)] == [0] * 200


@pytest.mark.parametrize("mean", (0.0, 0.25, 0.5, 0.75, 1.0))
def test_a_roll_is_always_a_whole_health_point_or_nothing(mean, seed_rng, sim_config):
    sim_config(UAV_COLLISION_DAMAGE_MEAN=mean)
    seed_rng(1)
    assert set(config.roll_collision_damage() for _ in range(500)) <= {0, 1}


@pytest.mark.parametrize("mean", (0.2, 0.5, 0.8))
def test_the_damage_averages_out_at_the_configured_mean(mean, seed_rng, sim_config):
    sim_config(UAV_COLLISION_DAMAGE_MEAN=mean)
    seed_rng(7)

    rolls = [config.roll_collision_damage() for _ in range(4000)]

    # 4000 draws put the standard error of the mean at under 0.01, so 0.05 is a wide margin
    assert abs(sum(rolls) / len(rolls) - mean) < 0.05


@pytest.mark.parametrize("mean, expected", ((-1.0, 0), (4.0, 1)))
def test_a_mean_outside_the_unit_interval_is_clamped(mean, expected, seed_rng, sim_config):
    sim_config(UAV_COLLISION_DAMAGE_MEAN=mean)
    seed_rng(2)
    assert [config.roll_collision_damage() for _ in range(100)] == [expected] * 100


def test_a_collision_that_rolls_no_damage_still_counts_as_a_collision(fleet):
    model = fleet(count=2, UAV_COLLISION_DAMAGE_MEAN=0.0)
    place(model, [(4, 4), (4, 4)])

    model.resolve_collisions()

    # the team flew into itself, which is worth reporting even when nobody was hurt by it
    assert model.collisions == 1
    assert [uav.hp for uav in model.uavs] == [3, 3]
    assert model.uavs_lost == 0


def test_a_cheap_collision_does_not_always_destroy_a_uav(fleet, seed_rng):
    # a mean of 0.5 with one health point each: some pairs are wiped out by their first collision and
    # others walk away from it, which is the whole point of rolling for the damage
    survived_first = 0
    for seed in range(20):
        model = fleet(count=2, UAV_HP=1, UAV_COLLISION_DAMAGE_MEAN=0.5, policy=ScriptedPolicy())
        seed_rng(seed)
        place(model, [(4, 4), (4, 4)])

        model.step()
        if model.active_uavs():
            survived_first += 1

    # both outcomes have to show up: at a mean of 0.5 a pair survives its first collision three times in
    # four, so seeing none of either over twenty runs would mean the roll is not happening
    assert 0 < survived_first < 20, f"{survived_first}/20 pairs survived their first collision"


def test_a_cheap_collision_still_destroys_a_uav_eventually(fleet, seed_rng):
    model = fleet(count=2, UAV_HP=1, UAV_COLLISION_DAMAGE_MEAN=0.5, policy=ScriptedPolicy())
    seed_rng(4)
    place(model, [(4, 4), (4, 4)])

    # stacked and holding position, so they collide every step until the rolls land
    for _ in range(60):
        model.step()
        if not model.active_uavs():
            break

    assert model.active_uavs() == []
    assert model.uavs_lost == 2


# --- the home base is shared airspace ---------------------------------------


def test_uavs_do_not_collide_on_the_home_base(fleet):
    model = fleet(count=4, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), NUM_OUT_BUILDINGS=0)
    # deliberately stacked on the anchor, which is what happens when UAVs come back to refill together
    place(model, [model.base.pos] * 4)

    model.resolve_collisions()

    assert [uav.hp for uav in model.uavs] == [3, 3, 3, 3]
    assert model.collisions == 0


def test_the_whole_base_footprint_is_shared_not_only_its_anchor(fleet):
    model = fleet(count=2, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2),
                  NUM_OUT_BUILDINGS=0)
    corner = model.base.cells[-1]
    assert corner != model.base.pos
    place(model, [corner, corner])

    model.resolve_collisions()

    assert [uav.hp for uav in model.uavs] == [3, 3]
    assert model.collisions == 0


def test_a_uav_flies_over_the_base_without_stopping_on_traffic(fleet):
    model = fleet(count=2, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(4, 4), BASE_SIZE=(1, 1),
                  NUM_OUT_BUILDINGS=0)
    flyer, parked = model.uavs
    model.grid.move_agent(flyer, (2, 4))
    model.grid.move_agent(parked, (4, 4))

    flyer.selected_dir, flyer.selected_speed = ACTION_RIGHT, 4

    # the base cell holds another UAV, but neither stops the flight nor costs anybody health points
    assert flyer.move() == 4
    assert flyer.pos == (6, 4)
    model.resolve_collisions()
    assert [uav.hp for uav in model.uavs] == [3, 3]


def test_a_collision_just_outside_the_base_still_counts(fleet):
    model = fleet(count=2, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2),
                  NUM_OUT_BUILDINGS=0)
    outside = (4, 2)  # one cell past the eastern edge of the footprint
    assert not model.base.covers(outside)
    place(model, [outside, outside])

    model.resolve_collisions()

    assert [uav.hp for uav in model.uavs] == [2, 2]
    assert model.collisions == 1


# --- launching from the base ------------------------------------------------


def test_the_team_is_spread_over_the_base_footprint(fleet):
    model = fleet(count=4, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2),
                  NUM_OUT_BUILDINGS=0)

    # a cell each, so the whole team is visible on the map from the first step rather than stacked
    positions = [uav.pos for uav in model.uavs]
    assert len(set(positions)) == 4
    assert set(positions) == set(model.base.cells)
    # UAV 0 keeps the anchor, which is where the base agent itself sits
    assert model.uavs[0].pos == model.base.pos


def test_a_team_smaller_than_the_base_starts_at_the_anchor_end(fleet):
    model = fleet(count=2, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2),
                  NUM_OUT_BUILDINGS=0)

    assert [uav.pos for uav in model.uavs] == model.base.cells[:2]


def test_a_team_larger_than_the_base_spills_over_around_it(fleet):
    model = fleet(count=6, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2),
                  NUM_OUT_BUILDINGS=0)

    positions = [uav.pos for uav in model.uavs]
    # six UAVs over a four cell base: a cell each all the same, the base first and then its surroundings
    assert len(set(positions)) == 6
    assert set(positions[:4]) == set(model.base.cells)
    for position in positions[4:]:
        assert not model.base.covers(position)
        # one of the cells touching the footprint, rather than anywhere on the map
        assert position in model.launch_ring((2, 2, 3, 3), 1)

    model.resolve_collisions()
    assert model.collisions == 0
    assert [uav.hp for uav in model.uavs] == [3] * 6


def test_the_overflow_fills_the_cells_nearest_the_base_first(fleet):
    # a 1x1 base ringed by 8 cells, then 16 more: a team of 12 takes the base, the whole first ring and
    # three of the second, and none of the second before the first is full
    model = fleet(count=12, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(4, 4), BASE_SIZE=(1, 1),
                  NUM_OUT_BUILDINGS=0)

    positions = [uav.pos for uav in model.uavs]
    box = (4, 4, 4, 4)
    assert len(set(positions)) == 12
    assert positions[0] == (4, 4)
    assert set(positions[1:9]) == set(model.launch_ring(box, 1))
    assert set(positions[9:]) <= set(model.launch_ring(box, 2))


def test_a_single_cell_base_still_launches_the_whole_team(fleet):
    model = fleet(count=3, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(1, 1),
                  NUM_OUT_BUILDINGS=0)

    # the anchor holds one UAV, and the other two stand next to it rather than on top of it
    assert model.uavs[0].pos == (2, 2)
    assert len(set(uav.pos for uav in model.uavs)) == 3
    model.resolve_collisions()
    assert model.collisions == 0


def test_the_overflow_is_clipped_to_the_grid(fleet):
    # a base in the corner of the 9x9 grid: the rings round it run off the map on two sides
    model = fleet(count=10, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(0, 0), BASE_SIZE=(1, 1),
                  NUM_OUT_BUILDINGS=0)

    positions = [uav.pos for uav in model.uavs]
    assert len(set(positions)) == 10
    assert all(not model.grid.out_of_bounds(position) for position in positions)


def test_a_team_larger_than_the_grid_is_refused(fleet):
    # 82 UAVs on 81 cells: there is no way to launch them unstacked, so the model says so
    with pytest.raises(ValueError, match="do not fit"):
        fleet(count=82, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2),
              NUM_OUT_BUILDINGS=0)


def test_the_team_gathers_round_the_grid_centre_without_a_base(fleet):
    # with the extension off there is no base, and the centre of the grid stands in for it
    model = fleet(count=12, ACTIVATE_FIREFIGHTING=False)

    positions = [uav.pos for uav in model.uavs]
    assert model.base is None
    assert len(set(positions)) == 12
    assert positions[0] == (4, 4)
    assert all(not model.grid.out_of_bounds(position) for position in positions)


# --- being destroyed --------------------------------------------------------


def test_a_uav_out_of_health_points_leaves_the_simulation(fleet):
    model = fleet(count=2, UAV_HP=1)
    place(model, [(4, 4), (4, 4)])

    model.resolve_collisions()

    assert model.uavs_lost == 2
    for uav in model.uavs:
        assert not uav.is_alive()
        # off the grid and out of the scheduler, so it is neither drawn nor stepped again
        assert uav.pos is None
        assert uav not in model.schedule.agents
    assert model.active_uavs() == []


def test_the_team_list_keeps_a_destroyed_uav_as_a_record(fleet):
    model = fleet(count=2, UAV_HP=1)
    before = list(model.uavs)
    place(model, [(4, 4), (4, 4)])

    model.resolve_collisions()

    assert model.uavs == before
    assert model.uav_by_id(before[0].unique_id) is before[0]


def test_a_destroyed_uav_neither_observes_nor_is_given_actions(fleet):
    model = fleet(count=3, UAV_HP=1)
    survivor = model.uavs[2]
    place(model, [(4, 4), (4, 4), (7, 7)])

    model.resolve_collisions()
    assert model.active_uavs() == [survivor]

    observations = model.observations()
    assert [observation.uav_id for observation in observations] == [survivor.unique_id]


def test_a_destroyed_uav_stops_moving_and_the_survivors_carry_on(fleet):
    model = fleet(count=3, UAV_HP=1)
    survivor = model.uavs[2]
    place(model, [(4, 4), (4, 4), (7, 7)])

    model.resolve_collisions()
    # the survivor is the only UAV left flying, so it is the one the first scripted action reaches
    model.policy = ScriptedPolicy({0: Action(ACTION_LEFT, 2)})

    model.step()

    assert survivor.pos == (5, 7)
    assert all(uav.pos is None for uav in model.uavs[:2])


def test_a_destroyed_uav_stops_scoring_but_keeps_what_it_earned(fleet):
    model = fleet(count=2, UAV_HP=1, FIRE_START_STEP=0, FIRE_START_POSITION=(4, 4),
                  policy=ScriptedPolicy({}))

    model.step()  # both UAVs still fly and score
    scores_before = list(model.MR1_LIST)
    assert all(score > 0 for score in scores_before)

    place(model, [(4, 4), (4, 4)])
    model.resolve_collisions()
    model.step()

    # the two destroyed UAVs keep the score they earned, and the list stays one entry per team member
    assert len(model.MR1_LIST) == 2
    assert model.MR1_LIST == scores_before


def test_the_run_survives_losing_the_whole_fleet(fleet):
    model = fleet(count=2, UAV_HP=1, policy=ScriptedPolicy({}))
    place(model, [(4, 4), (4, 4)])
    model.resolve_collisions()

    for _ in range(3):  # the wildfire keeps burning with nobody watching it
        model.step()

    assert model.running
    assert model.active_uavs() == []


def test_a_uav_destroyed_at_the_base_frees_its_refill_slot(fleet):
    model = fleet(count=2, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(1, 1),
                  NUM_OUT_BUILDINGS=0, UAV_HP=1)
    doomed = model.uavs[0]
    model.base.serving[doomed.unique_id] = 5

    model.destroy_uav(doomed)

    assert doomed.unique_id not in model.base.serving
    # the base steps without tripping over a UAV that has no position left
    model.base.step()


# --- the security distance is not the collision rule ------------------------


def test_flying_closer_than_the_security_distance_costs_no_health(fleet):
    # well inside SECURITY_DISTANCE of each other, but on cells of their own, and holding them
    model = fleet(count=2, SECURITY_DISTANCE=10, policy=ScriptedPolicy())
    place(model, [(4, 4), (5, 4)])

    model.step()

    assert [uav.hp for uav in model.uavs] == [3, 3]
    assert model.collisions == 0
    # MR2 still records the proximity, which is what it is for
    assert model.MR2_VALUE == 1


def test_a_collision_is_counted_whatever_the_security_distance_is(fleet):
    model = fleet(count=2, SECURITY_DISTANCE=0, policy=ScriptedPolicy())  # nobody moves apart
    place(model, [(4, 4), (4, 4)])

    model.step()

    assert model.collisions == 1
    assert model.MR2_VALUE == 0  # no pair is closer than a security distance of zero


def test_the_security_distance_does_not_stop_a_uav_from_flying(fleet):
    model = fleet(count=2, SECURITY_DISTANCE=20)  # larger than the grid
    flyer, other = model.uavs
    model.grid.move_agent(flyer, (0, 4))
    model.grid.move_agent(other, (8, 8))

    flyer.selected_dir, flyer.selected_speed = ACTION_RIGHT, 5

    assert flyer.move() == 5
    assert flyer.pos == (5, 4)


def test_a_lone_uav_can_neither_collide_nor_score_mr2(fleet):
    model = fleet(count=1)
    model.step()

    assert model.collisions == 0
    assert model.MR2_VALUE == 0
    assert model.uavs[0].is_alive()


# --- what a policy is told about the traffic --------------------------------


def test_a_uav_sees_the_other_uavs_inside_its_observation_window(fleet):
    model = fleet(count=3, UAV_OBSERVATION_RADIUS=2)
    watcher, near, far = model.uavs
    place(model, [(4, 4), (5, 5), (8, 8)])

    observation = watcher.observe()

    # the neighbour is in the window, the third UAV is outside it, and a UAV never reports itself
    assert observation.uav_positions == [(5, 5)]
    assert observation.occupied((5, 5))
    assert not observation.occupied((4, 4))
    assert not observation.occupied((8, 8))


def test_a_destroyed_uav_is_no_longer_reported_as_traffic(fleet):
    model = fleet(count=3, UAV_HP=1)
    watcher = model.uavs[0]
    place(model, [(2, 2), (4, 4), (4, 4)])

    model.resolve_collisions()  # the other two wipe each other out

    assert watcher.observe().uav_positions == []


def test_the_uavs_in_view_are_reported_with_the_extension_switched_off(fleet):
    model = fleet(count=2, ACTIVATE_FIREFIGHTING=False)
    watcher = model.uavs[0]
    place(model, [(4, 4), (5, 4)])

    observation = watcher.observe()

    # collisions are not part of the firefighting extension, so the traffic is reported either way
    assert observation.uav_positions == [(5, 4)]
    assert observation.base_footprint() == []


def test_a_uav_is_told_the_whole_base_footprint(fleet):
    model = fleet(count=1, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2),
                  NUM_OUT_BUILDINGS=0)
    observation = model.uavs[0].observe()

    assert set(observation.base_footprint()) == set(model.base.cells)
    assert observation.at_base()


# --- the firefighter policy keeps its team apart ----------------------------


def test_the_firefighter_fleet_survives_a_run(make_model):
    # every UAV starts on the base and heads for the same fire, which used to wipe the fleet out
    model = make_model(policy="firefighter", NUM_AGENTS=4, HEIGHT=20, WIDTH=20,
                       ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), NUM_OUT_BUILDINGS=2,
                       FIRE_START_POSITION=(12, 12), FIRE_START_STEP=0, UAV_SPEED=3, UAV_HP=3)

    for _ in range(40):
        model.step()

    assert model.collisions == 0, "the firefighter policy flew its own UAVs into each other"
    assert model.uavs_lost == 0
    assert len(model.active_uavs()) == 4
