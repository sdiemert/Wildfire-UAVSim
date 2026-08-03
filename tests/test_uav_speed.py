"""Tests for UAV speed: how far a UAV actually flies once a policy has asked for a direction and a speed.

These build a real WildFireModel, because covering several cells depends on the grid: the UAV has to stop
at the edge of it, and in front of another UAV.

Direction reminder, from the movement vectors in UAV.move():
    ACTION_RIGHT  x + 1        ACTION_LEFT  x - 1
    ACTION_UP     y + 1        ACTION_DOWN  y - 1
"""

# python libraries

import pytest

# own python modules

import agents

from config import ACTION_DUMP_WATER, ACTION_LEFT, ACTION_RIGHT, ACTION_STAY, ACTION_UP

from policy import Action, Policy


# --- helpers ----------------------------------------------------------------


class FixedPolicy(Policy):
    """Gives every UAV the same action, so that a test can drive the fleet from the model level."""

    name = "fixed"

    def __init__(self, action):
        self.action = action

    def select_actions(self, observations):
        return [self.action for _ in observations]


def uavs_of(model):
    return [agent for agent in model.schedule.agents if type(agent) is agents.UAV]


@pytest.fixture
def uav(make_model):
    """One UAV on a 9x9 grid, placed where the test asks, with the fleet speed pinned."""

    def _make(pos, speed=5, **overrides):
        settings = {"NUM_AGENTS": 1, "UAV_SPEED": speed, "ACTIVATE_FIREFIGHTING": False}
        settings.update(overrides)
        model = make_model(**settings)
        drone = uavs_of(model)[0]
        model.grid.move_agent(drone, pos)
        return model, drone

    return _make


# --- covering several cells in one step -------------------------------------


def test_a_uav_covers_the_whole_speed_it_was_given(uav):
    model, drone = uav(pos=(2, 4))
    drone.selected_dir, drone.selected_speed = ACTION_RIGHT, 3

    assert drone.move() == 3
    assert drone.pos == (5, 4)


def test_speed_one_is_the_original_single_cell_step(uav):
    model, drone = uav(pos=(4, 4))
    drone.selected_dir, drone.selected_speed = ACTION_UP, 1

    assert drone.move() == 1
    assert drone.pos == (4, 5)


def test_a_uav_never_flies_further_than_uav_speed(uav):
    # the policy asks for ten cells, the airframe only does three
    model, drone = uav(pos=(0, 4), speed=3)
    drone.selected_dir, drone.selected_speed = ACTION_RIGHT, 10

    assert drone.move() == 3
    assert drone.pos == (3, 4)


def test_zero_speed_holds_position(uav):
    model, drone = uav(pos=(4, 4))
    drone.selected_dir, drone.selected_speed = ACTION_RIGHT, 0

    assert drone.move() == 0
    assert drone.pos == (4, 4)


def test_a_grounded_fleet_cannot_move(uav):
    model, drone = uav(pos=(4, 4), speed=0)
    drone.selected_dir, drone.selected_speed = ACTION_RIGHT, 5

    assert drone.move() == 0
    assert drone.pos == (4, 4)


def test_holding_position_ignores_the_speed(uav):
    model, drone = uav(pos=(4, 4))
    drone.selected_dir, drone.selected_speed = ACTION_STAY, 4

    assert drone.move() == 0
    assert drone.pos == (4, 4)


# --- stopping early ---------------------------------------------------------


def test_a_uav_stops_at_the_edge_of_the_grid(uav):
    # two cells from the eastern edge, asked for five
    model, drone = uav(pos=(6, 4))
    drone.selected_dir, drone.selected_speed = ACTION_RIGHT, 5

    assert drone.move() == 2
    assert drone.pos == (8, 4)


def test_a_uav_already_against_the_edge_does_not_move(uav):
    model, drone = uav(pos=(8, 4))
    drone.selected_dir, drone.selected_speed = ACTION_RIGHT, 5

    assert drone.move() == 0
    assert drone.pos == (8, 4)


def test_a_uav_flies_into_another_uav_instead_of_jumping_over_it(uav):
    model, drone = uav(pos=(2, 4), NUM_AGENTS=2)
    blocker = uavs_of(model)[1]
    model.grid.move_agent(blocker, (5, 4))

    drone.selected_dir, drone.selected_speed = ACTION_RIGHT, 5

    # it covers the two free cells and takes the occupied one, which is a collision (see
    # tests/test_uav_collisions.py); the flight ends there rather than carrying on over it
    assert drone.move() == 3
    assert drone.pos == (5, 4)
    assert blocker.pos == (5, 4)


# --- the action a policy returns reaches the UAV ----------------------------


def test_the_model_hands_the_policy_direction_and_speed_to_each_uav(make_model):
    model = make_model(NUM_AGENTS=2, UAV_SPEED=6, ACTIVATE_FIREFIGHTING=False,
                       policy=FixedPolicy(Action(ACTION_LEFT, 4)))
    model.step()

    for drone in uavs_of(model):
        assert drone.selected_dir == ACTION_LEFT
        assert drone.selected_speed == 4


def test_a_policy_that_only_gives_a_direction_still_flies_one_cell(make_model):
    # what every policy returned before speeds existed
    model = make_model(NUM_AGENTS=1, UAV_SPEED=5, ACTIVATE_FIREFIGHTING=False,
                       policy=FixedPolicy(ACTION_UP))
    drone = uavs_of(model)[0]
    model.grid.move_agent(drone, (4, 2))

    model.step()
    assert drone.selected_speed == 1
    assert drone.pos == (4, 3)


def test_a_policy_may_return_a_direction_and_speed_pair(make_model):
    model = make_model(NUM_AGENTS=1, UAV_SPEED=5, ACTIVATE_FIREFIGHTING=False,
                       policy=FixedPolicy((ACTION_UP, 3)))
    drone = uavs_of(model)[0]
    model.grid.move_agent(drone, (4, 2))

    model.step()
    assert drone.pos == (4, 5)


def test_a_uav_flies_its_speed_on_every_step(make_model):
    model = make_model(NUM_AGENTS=1, UAV_SPEED=2, ACTIVATE_FIREFIGHTING=False,
                       policy=FixedPolicy(Action(ACTION_UP, 2)))
    drone = uavs_of(model)[0]
    model.grid.move_agent(drone, (4, 0))

    for expected in (2, 4, 6, 8):
        model.step()
        assert drone.pos == (4, expected)


# --- the firefighting extension is unaffected -------------------------------


def test_dumping_water_takes_the_whole_step_whatever_the_speed(make_model):
    model = make_model(NUM_AGENTS=1, UAV_SPEED=5, ACTIVATE_FIREFIGHTING=True,
                       NUM_OUT_BUILDINGS=0, BASE_POSITION=(4, 4),
                       policy=FixedPolicy(Action(ACTION_DUMP_WATER, 5)))
    drone = uavs_of(model)[0]
    position = drone.pos

    model.step()
    assert drone.pos == position
    assert not drone.has_water()
