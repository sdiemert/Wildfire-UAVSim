"""Tests for SuperPolicy: flying a team under several policies at once, and keeping it apart."""

# python libraries

import pytest

# own python modules

import config

from config import ACTION_STAY
from sim.policy import Action, Observation, PolicyParams, Policy, SuperPolicy


# a policy that always asks for the same thing, so a test can see exactly where its actions ended up
class Fixed(Policy):
    def __init__(self, name, action):
        self.name = name
        self.action = action
        self.seen = []

    def select_actions(self, observations):
        self.seen.append([observation.uav_id for observation in observations])
        return [self.action for _ in observations]


@pytest.fixture
def super_policy():
    """A SuperPolicy over stub policies, so the tests are about dispatch rather than about firefighting."""
    built = {
        "alpha": Fixed("alpha", Action(config.ACTION_RIGHT, 1)),
        "beta": Fixed("beta", Action(config.ACTION_LEFT, 1)),
        "still": Fixed("still", Action.stay()),
    }
    policy = SuperPolicy(default="alpha", build=lambda name: built[name])
    policy.stubs = built
    return policy


def observations(*positions, **kwargs):
    return [Observation(uav_id=index, pos=pos, **kwargs) for index, pos in enumerate(positions)]


# --- the table --------------------------------------------------------------


def test_an_unallocated_uav_flies_the_default(super_policy):
    assert super_policy.allocated(0) == ("alpha", PolicyParams())


def test_assigning_changes_what_a_uav_flies(super_policy):
    assert super_policy.assign(0, "beta") is True
    assert super_policy.allocated(0)[0] == "beta"


def test_assigning_the_same_thing_twice_changes_nothing(super_policy):
    super_policy.assign(0, "beta")
    assert super_policy.assign(0, "beta") is False, "an unchanged allocation is not an adaptation"


def test_the_assignment_can_be_read_back(super_policy):
    super_policy.assign(1, "beta", PolicyParams(separation=2))
    assert super_policy.assignment() == {1: ("beta", PolicyParams(separation=2))}


# --- dispatch ---------------------------------------------------------------


def test_each_uav_gets_the_policy_it_was_allocated(super_policy, sim_config):
    sim_config(UAV_SPEED=5, UAV_OBSERVATION_RADIUS=4)
    super_policy.assign(0, "alpha")
    super_policy.assign(1, "beta")

    actions = super_policy.select_actions(observations((5, 5), (20, 20)))
    assert actions[0].direction == config.ACTION_RIGHT
    assert actions[1].direction == config.ACTION_LEFT


def test_actions_come_back_in_team_order(super_policy, sim_config):
    sim_config(UAV_SPEED=5, UAV_OBSERVATION_RADIUS=4)
    # interleaved so that a reassembly bug cannot pass by accident
    for uav_id, name in ((0, "beta"), (1, "alpha"), (2, "beta"), (3, "alpha")):
        super_policy.assign(uav_id, name)

    actions = super_policy.select_actions(observations((0, 0), (10, 10), (20, 20), (30, 30)))
    assert [action.direction for action in actions] == [
        config.ACTION_LEFT, config.ACTION_RIGHT, config.ACTION_LEFT, config.ACTION_RIGHT]


# grouping is what preserves the team level reasoning the basic policies already do: FirefighterPolicy can
# only avoid sending two UAVs to one fire if it is shown both of them in the same call
def test_uavs_on_one_policy_are_handed_over_together(super_policy, sim_config):
    sim_config(UAV_SPEED=5, UAV_OBSERVATION_RADIUS=4)
    for uav_id in (0, 2):
        super_policy.assign(uav_id, "alpha")
    super_policy.assign(1, "beta")

    super_policy.select_actions(observations((0, 0), (10, 10), (20, 20)))
    assert super_policy.stubs["alpha"].seen == [[0, 2]], "both alpha UAVs in one call"
    assert super_policy.stubs["beta"].seen == [[1]]


def test_uavs_with_different_parameters_are_not_grouped(super_policy, sim_config):
    sim_config(UAV_SPEED=5, UAV_OBSERVATION_RADIUS=4)
    super_policy.assign(0, "alpha", PolicyParams(separation=1))
    super_policy.assign(1, "alpha", PolicyParams(separation=4))

    super_policy.select_actions(observations((0, 0), (20, 20)))
    assert sorted(super_policy.stubs["alpha"].seen) == [[0], [1]]


def test_a_policy_returning_the_wrong_number_of_actions_is_reported_against_itself(super_policy):
    class Broken(Policy):
        name = "broken"

        def select_actions(self, observations):
            return []

    super_policy.build = lambda name: Broken()
    super_policy.instances.clear()
    super_policy.assign(0, "broken")
    with pytest.raises(ValueError, match="broken"):
        super_policy.select_actions(observations((5, 5)))


def test_no_uavs_means_no_actions(super_policy):
    assert super_policy.select_actions([]) == []


# --- the fleet wide traffic pass --------------------------------------------


def test_a_uav_is_held_to_the_speed_it_was_allocated(super_policy, sim_config):
    sim_config(UAV_SPEED=5, UAV_OBSERVATION_RADIUS=5)
    super_policy.stubs["alpha"].action = Action(config.ACTION_RIGHT, 5)
    super_policy.assign(0, "alpha", PolicyParams(speed_cap=2))

    assert super_policy.select_actions(observations((5, 5)))[0].speed == 2


def test_a_uav_is_never_sent_further_than_it_can_see(super_policy, sim_config):
    sim_config(UAV_SPEED=9, UAV_OBSERVATION_RADIUS=3)
    super_policy.stubs["alpha"].action = Action(config.ACTION_RIGHT, 9)
    super_policy.assign(0, "alpha")
    # a flight ending outside the observation window lands on a cell the UAV was told nothing about
    assert super_policy.select_actions(observations((5, 5)))[0].speed == 3


def test_a_uav_stops_short_of_one_it_can_see(super_policy, sim_config):
    sim_config(UAV_SPEED=5, UAV_OBSERVATION_RADIUS=5)
    super_policy.stubs["alpha"].action = Action(config.ACTION_RIGHT, 3)
    super_policy.assign(0, "alpha")

    # a team mate two cells to the right: the UAV may cover one cell and no more
    actions = super_policy.select_actions([Observation(uav_id=0, pos=(5, 5), uav_positions=[(7, 5)])])
    assert actions[0].speed == 1


# this is what SuperPolicy adds that no basic policy can: FirefighterPolicy deconflicts its own team, but
# has no way of knowing about a UAV flying defend-base on the next cell, because that UAV was never in its
# call. Without a fleet wide pass a mixed allocation would collide more than either policy does alone.
def test_two_uavs_on_different_policies_are_not_sent_to_the_same_cell(super_policy, sim_config):
    sim_config(UAV_SPEED=5, UAV_OBSERVATION_RADIUS=5)
    super_policy.stubs["alpha"].action = Action(config.ACTION_RIGHT, 1)   # (5, 5) -> (6, 5)
    super_policy.stubs["beta"].action = Action(config.ACTION_LEFT, 1)     # (7, 5) -> (6, 5)
    super_policy.assign(0, "alpha")
    super_policy.assign(1, "beta")

    actions = super_policy.select_actions(observations((5, 5), (7, 5)))
    landings = {(5 + actions[0].speed, 5) if actions[0].is_movement() else (5, 5),
                (7 - actions[1].speed, 5) if actions[1].is_movement() else (7, 5)}
    assert len(landings) == 2, "the two UAVs must not end the step on the same cell"


def test_a_separation_of_its_own_keeps_a_uav_further_off(super_policy, sim_config):
    sim_config(UAV_SPEED=5, UAV_OBSERVATION_RADIUS=5)
    super_policy.stubs["alpha"].action = Action(config.ACTION_RIGHT, 4)
    super_policy.assign(0, "alpha", PolicyParams(separation=2))

    # a team mate at (9, 5); with a 2 cell cushion the UAV must stop before (7, 5)
    actions = super_policy.select_actions([Observation(uav_id=0, pos=(5, 5), uav_positions=[(9, 5)])])
    assert 5 + actions[0].speed < 7


# the home base is shared airspace: blocking it would leave the team circling its own base instead of
# queueing on it to refill
def test_the_home_base_is_never_blocked(super_policy, sim_config):
    sim_config(UAV_SPEED=5, UAV_OBSERVATION_RADIUS=5)
    super_policy.stubs["alpha"].action = Action(config.ACTION_RIGHT, 2)
    super_policy.assign(0, "alpha")

    actions = super_policy.select_actions([Observation(
        uav_id=0, pos=(5, 5), uav_positions=[(7, 5)], base_cells=[(6, 5), (7, 5)])])
    assert actions[0].speed == 2, "UAVs neither collide nor stop over the base"


def test_an_action_that_does_not_move_is_left_alone(super_policy, sim_config):
    sim_config(UAV_SPEED=5, UAV_OBSERVATION_RADIUS=5)
    super_policy.assign(0, "still")
    assert super_policy.select_actions(observations((5, 5)))[0].direction == ACTION_STAY


# --- against the real policies ----------------------------------------------


def test_a_uniform_allocation_behaves_exactly_like_that_policy_on_its_own(sim_config, seed_rng):
    """The managed system with everyone on one policy must be the simulation as it always was."""
    sim_config(UAV_SPEED=3, UAV_OBSERVATION_RADIUS=4, ACTIVATE_FIREFIGHTING=True)
    from sim.policy import FirefighterPolicy

    scenario = [Observation(uav_id=0, pos=(5, 5), cells=[((6, 5), 1)], has_water=True,
                            base_cells=[(1, 1)], base_pos=(1, 1)),
                Observation(uav_id=1, pos=(9, 9), cells=[((9, 8), 1)], has_water=True,
                            base_cells=[(1, 1)], base_pos=(1, 1))]

    seed_rng(0)
    direct = FirefighterPolicy().select_actions(scenario)
    seed_rng(0)
    through_super = SuperPolicy(default="firefighter").select_actions(scenario)

    assert through_super == direct


def test_the_default_policy_has_to_exist():
    with pytest.raises(KeyError, match="firefighter"):
        SuperPolicy(default="no-such-policy")


def test_it_describes_its_allocation_for_the_log():
    policy = SuperPolicy(default="firefighter")
    assert "firefighter for all" in str(policy)
    policy.assign(0, "disperse")
    policy.assign(1, "disperse")
    assert "2xdisperse" in str(policy)
