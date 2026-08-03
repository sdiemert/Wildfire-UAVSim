"""Tests for FirefighterPolicy, the policy of the firefighting extension.

These are pure policy tests: they build Observations directly and never touch the grid.

Most of them assert only the direction, because the distances involved are derived from
WATER_DROP_RADIUS and would make the expected speed depend on config.py. The speeds have a section of
their own at the end, where both constants are pinned.
"""

# python libraries

import pytest

# own python modules

import config

from config import ACTION_DOWN, ACTION_DUMP_WATER, ACTION_LEFT, ACTION_RIGHT, ACTION_STAY, ACTION_UP

from sim.policy import Action, FirefighterPolicy, avoid, flight_path


@pytest.fixture
def policy():
    return FirefighterPolicy()


def directions(actions):
    """The direction of each action, for the tests that only care about which way the UAV flies."""
    return [action.direction for action in actions]


# --- with an empty tank the UAV goes home -----------------------------------


def test_empty_uav_flies_back_to_the_base(policy, observation):
    obs = observation(pos=(5, 5), burning=[(6, 5)], base_pos=(1, 5), has_water=False)
    # the fire is right there, but with no water the only useful thing to do is refill
    assert directions(policy.select_actions([obs])) == [ACTION_LEFT]


def test_empty_uav_waits_at_the_base_while_it_refills(policy, observation):
    obs = observation(pos=(1, 5), base_pos=(1, 5), has_water=False)
    # refilling is not an action: standing still on the base is what triggers it
    assert directions(policy.select_actions([obs])) == [ACTION_STAY]


def test_empty_uav_without_a_base_holds_position(policy, observation):
    # happens when the policy is selected while the extension is switched off
    obs = observation(pos=(5, 5), burning=[(6, 5)], has_water=False)
    assert directions(policy.select_actions([obs])) == [ACTION_STAY]


# --- with water the UAV attacks the fire ------------------------------------


def test_dumps_water_when_the_fire_is_within_drop_range(policy, observation):
    obs = observation(pos=(5, 5), burning=[(5, 5)], base_pos=(1, 1), has_water=True)
    assert directions(policy.select_actions([obs])) == [ACTION_DUMP_WATER]


def test_dumps_water_on_a_fire_at_the_edge_of_the_drop_radius(policy, observation):
    fire = (5 + config.WATER_DROP_RADIUS, 5)
    obs = observation(pos=(5, 5), burning=[fire], base_pos=(1, 1), has_water=True)
    assert directions(policy.select_actions([obs])) == [ACTION_DUMP_WATER]


def test_flies_toward_a_fire_that_is_out_of_drop_range(policy, observation):
    fire = (5 + config.WATER_DROP_RADIUS + 2, 5)
    obs = observation(pos=(5, 5), burning=[fire], base_pos=(1, 1), has_water=True)
    assert directions(policy.select_actions([obs])) == [ACTION_RIGHT]


def test_holds_position_when_there_is_nothing_to_extinguish(policy, observation):
    obs = observation(pos=(5, 5), unburnt=[(4, 5), (6, 5)], base_pos=(1, 1), has_water=True)
    assert directions(policy.select_actions([obs])) == [ACTION_STAY]


def test_targets_the_nearest_fire(policy, observation):
    far = (5, 5 - config.WATER_DROP_RADIUS - 4)
    near = (5, 5 + config.WATER_DROP_RADIUS + 1)
    obs = observation(pos=(5, 5), burning=[far, near], base_pos=(1, 1), has_water=True)
    assert directions(policy.select_actions([obs])) == [ACTION_UP]


# --- protecting the out buildings -------------------------------------------


def test_defends_a_threatened_building_over_closer_open_vegetation(policy, observation):
    # a fire two cells away on one side, and a fire right next to a building further away on the other
    building = (5, 12)
    fire_near_building = (5, 11)
    closer_fire = (1, 5)
    obs = observation(pos=(5, 5), burning=[closer_fire, fire_near_building],
                      building_positions=[building], base_pos=(1, 1), has_water=True)
    # heads for the building rather than the nearer fire
    assert directions(policy.select_actions([obs])) == [ACTION_UP]


def test_ignores_buildings_that_are_not_threatened(policy, observation):
    # the building is in view but no fire is anywhere near it, so the nearest fire wins
    obs = observation(pos=(5, 5), burning=[(1, 5)], building_positions=[(5, 20)],
                      base_pos=(1, 1), has_water=True)
    assert directions(policy.select_actions([obs])) == [ACTION_LEFT]


# --- several UAVs -----------------------------------------------------------


def test_returns_one_action_per_uav_in_order(policy, observation):
    observations = [
        observation(pos=(5, 5), burning=[(5, 5)], base_pos=(1, 1), has_water=True, uav_id=0),
        observation(pos=(5, 5), base_pos=(5, 1), has_water=False, uav_id=1),
        observation(pos=(5, 5), base_pos=(1, 1), has_water=True, uav_id=2),
    ]
    assert directions(policy.select_actions(observations)) == [ACTION_DUMP_WATER, ACTION_DOWN, ACTION_STAY]


def test_no_uavs_gives_no_actions(policy):
    assert policy.select_actions([]) == []


# --- how fast the UAV flies -------------------------------------------------


def test_closes_the_whole_gap_to_the_base_in_one_step(policy, observation, uav_speed):
    uav_speed(6)
    obs = observation(pos=(5, 5), base_pos=(1, 5), has_water=False)
    # four cells to the west, and the UAV can cover six, so it lands on the base rather than short of it
    assert policy.select_actions([obs]) == [Action(ACTION_LEFT, 4)]


def test_never_asks_for_more_speed_than_a_uav_has(policy, observation, uav_speed):
    uav_speed(2)
    obs = observation(pos=(5, 5), base_pos=(0, 5), has_water=False)
    assert policy.select_actions([obs]) == [Action(ACTION_LEFT, 2)]


def test_dumping_water_and_waiting_carry_no_speed(policy, observation):
    dumping = observation(pos=(5, 5), burning=[(5, 5)], base_pos=(1, 1), has_water=True)
    waiting = observation(pos=(1, 5), base_pos=(1, 5), has_water=False)

    assert policy.select_actions([dumping, waiting]) == [Action.dump(), Action.stay()]


# --- keeping out of the way of a UAV in view --------------------------------


def test_stops_short_of_a_uav_standing_in_the_way(policy, observation, uav_speed):
    uav_speed(5)
    # the fire is five cells east, and a teammate is parked three cells along that line
    obs = observation(pos=(5, 5), burning=[(10, 5)], uavs=[(8, 5)], base_pos=(1, 1), has_water=True)

    assert policy.select_actions([obs]) == [Action(ACTION_RIGHT, 2)]


def test_holds_position_when_the_very_next_cell_is_taken(policy, observation, uav_speed):
    uav_speed(5)
    obs = observation(pos=(5, 5), burning=[(10, 5)], uavs=[(6, 5)], base_pos=(1, 1), has_water=True)

    assert policy.select_actions([obs]) == [Action.stay()]


def test_a_uav_off_the_flight_path_costs_no_speed(policy, observation, uav_speed, sim_config):
    uav_speed(5)
    sim_config(UAV_OBSERVATION_RADIUS=5)  # so that the sight limit below does not trim the flight instead
    # the teammate is beside the route rather than on it
    obs = observation(pos=(5, 5), burning=[(10, 5)], uavs=[(8, 6)], base_pos=(1, 1), has_water=True)

    assert policy.select_actions([obs]) == [Action(ACTION_RIGHT, 5)]


def test_a_uav_on_the_home_base_is_flown_over_rather_than_avoided(policy, observation, uav_speed):
    uav_speed(4)
    # heading home to refill, with a teammate already queueing on the base
    footprint = [(1, 5), (2, 5)]
    obs = observation(pos=(5, 5), uavs=[(2, 5)], base_pos=(1, 5), base_cells=footprint, has_water=False)

    # the base is shared airspace, so the UAV lands on it instead of stopping short and never refilling
    assert policy.select_actions([obs]) == [Action(ACTION_LEFT, 4)]


def test_a_uav_is_never_sent_further_than_it_can_see(policy, observation, uav_speed, sim_config):
    # a UAV that flies further than its observation window lands on a cell it was told nothing about,
    # where a teammate it never saw may be standing
    uav_speed(5)
    sim_config(UAV_OBSERVATION_RADIUS=3)
    obs = observation(pos=(5, 5), burning=[(15, 5)], base_pos=(1, 1), has_water=True)

    assert policy.select_actions([obs]) == [Action(ACTION_RIGHT, 3)]


def test_a_blind_uav_holds_position(policy, observation, uav_speed, sim_config):
    uav_speed(5)
    sim_config(UAV_OBSERVATION_RADIUS=0)
    obs = observation(pos=(5, 5), burning=[(15, 5)], base_pos=(1, 1), has_water=True)

    assert policy.select_actions([obs]) == [Action.stay()]


# --- keeping the team apart from each other ---------------------------------


def test_two_uavs_are_not_sent_to_the_same_fire(policy, observation, uav_speed):
    uav_speed(1)  # one cell a step, so neither reaches its fire this step
    fires = [(5, 11), (5, 2)]
    observations = [
        observation(pos=(5, 6), burning=fires, base_pos=(1, 1), has_water=True, uav_id=0),
        observation(pos=(5, 5), burning=fires, base_pos=(1, 1), has_water=True, uav_id=1),
    ]

    # (5, 2) is the nearest fire for both of them. The first UAV claims it and flies south; the second
    # gives it up and turns north for the other fire, which on its own it would have ignored.
    assert [action.direction for action in policy.select_actions(observations)] == [ACTION_DOWN, ACTION_UP]


def test_two_uavs_over_the_same_fire_do_not_both_dump_on_it(policy, observation):
    # both are right on top of one burning cell, and it is the only one in view
    obs = [observation(pos=(5, 5), burning=[(5, 5)], base_pos=(1, 1), has_water=True, uav_id=index)
           for index in range(2)]

    actions = policy.select_actions(obs)

    # the first puts it out; the second has nothing left to do rather than wasting its load on the same cell
    assert actions[0].direction == ACTION_DUMP_WATER
    assert actions[1] == Action.stay()


def test_each_uav_of_a_team_takes_a_fire_of_its_own(policy, observation):
    fires = [(5, 5), (6, 5), (7, 5)]
    obs = [observation(pos=cell, burning=fires, base_pos=(1, 1), has_water=True, uav_id=index)
           for index, cell in enumerate(fires)]

    # each of them is standing on a fire of its own, so all three dump rather than converging on one
    assert [action.direction for action in policy.select_actions(obs)] == [ACTION_DUMP_WATER] * 3


def test_two_uavs_are_not_sent_to_the_same_cell(policy, observation, uav_speed):
    uav_speed(3)
    # one fire each, but the routes to them end on the same cell
    observations = [
        observation(pos=(5, 2), burning=[(5, 9)], base_pos=(1, 1), has_water=True, uav_id=0),
        observation(pos=(5, 8), burning=[(5, 2)], base_pos=(1, 1), has_water=True, uav_id=1),
    ]

    first, second = policy.select_actions(observations)
    first_path = set(flight_path((5, 2), first))
    second_path = set(flight_path((5, 8), second))

    assert not first_path & second_path, "the two UAVs were sent through the same cells"


def test_a_team_with_nothing_in_view_holds_together_without_colliding(policy, observation):
    obs = [observation(pos=(5, 5), base_pos=(1, 1), has_water=True, uav_id=index) for index in range(3)]
    assert policy.select_actions(obs) == [Action.stay()] * 3


# --- the trimming helper itself ---------------------------------------------


def test_avoid_leaves_an_unobstructed_action_alone():
    action = Action(ACTION_RIGHT, 4)
    assert avoid((0, 0), action, {(0, 3), (9, 9)}) == action


def test_avoid_leaves_actions_that_do_not_move_alone():
    assert avoid((0, 0), Action.stay(), {(0, 0), (1, 1)}) == Action.stay()
    assert avoid((0, 0), Action.dump(), {(0, 0), (1, 1)}) == Action.dump()


def test_avoid_trims_to_the_cell_before_the_obstacle():
    assert avoid((0, 0), Action(ACTION_UP, 5), {(0, 4)}) == Action(ACTION_UP, 3)


def test_avoid_holds_position_when_there_is_no_room_at_all():
    assert avoid((0, 0), Action(ACTION_UP, 5), {(0, 1)}) == Action.stay()


def test_avoid_stops_at_the_first_obstacle_not_the_nearest_one_to_the_target():
    assert avoid((0, 0), Action(ACTION_DOWN, 5), {(0, -2), (0, -4)}) == Action(ACTION_DOWN, 1)


def test_flight_path_lists_the_cells_in_the_order_they_are_crossed():
    assert flight_path((2, 2), Action(ACTION_LEFT, 3)) == [(1, 2), (0, 2), (-1, 2)]
    assert flight_path((2, 2), Action.stay()) == []
