"""Tests for the UAV team list the model keeps, and the ordering everything else depends on.

WildFireModel.uavs holds the UAV agents so that the model does not have to pick them back out of a
scheduler that also holds one Fire agent per cell of the forest. Two things have to stay true for
that to be safe:

  * the list has to hold exactly the UAVs the scheduler holds, in the same order;
  * observations() and set_drone_dirs() both walk it, and a policy answers the first with a list of
    actions the second applies by position, so entry i of what the policy returned has to reach UAV i.

Every shipped configuration flies a single UAV, which would hide an ordering mistake, so these tests
fly several.
"""

# python libraries

import pytest

# own python modules

import agents

from config import ACTION_DOWN, ACTION_LEFT, ACTION_RIGHT, ACTION_UP

from sim.policy import Policy


# --- helpers ----------------------------------------------------------------


# the UAVs as found in the scheduler, which is where they used to be looked up from. Deliberately
# written the old way, so that it is an independent check on model.uavs rather than a restatement.
def uavs_in_scheduler(model):
    return [agent for agent in model.schedule.agents if type(agent) is agents.UAV]


class PerUAVPolicy(Policy):
    """Gives each UAV an action derived from its own id, so a mis-ordering is visible.

    A policy only ever sees observations, so if the actions came back in a different order from the
    UAVs they were built for, the action a UAV ends up with will not match its own id.
    """

    name = "per-uav"

    DIRECTIONS = (ACTION_RIGHT, ACTION_DOWN, ACTION_LEFT, ACTION_UP)

    def select_actions(self, observations):
        return [self.DIRECTIONS[observation.uav_id % len(self.DIRECTIONS)]
                for observation in observations]


@pytest.fixture
def fleet(make_model):
    """A model flying several UAVs, on a grid big enough that they are not all on top of each other."""

    def _make(count=4, **overrides):
        settings = {"NUM_AGENTS": count, "HEIGHT": 15, "WIDTH": 15,
                    "ACTIVATE_FIREFIGHTING": False, "FIRE_START_STEP": 10_000}
        settings.update(overrides)
        return make_model(**settings)

    return _make


# --- the list itself --------------------------------------------------------


def test_the_team_matches_the_scheduler(fleet):
    model = fleet(count=4)
    assert model.uavs == uavs_in_scheduler(model)


def test_the_team_matches_the_scheduler_with_firefighting_on(fleet):
    # the base and the out buildings are added to the scheduler before the UAVs, so this pins that
    # the ordering survives having other agent types interleaved
    model = fleet(count=3, ACTIVATE_FIREFIGHTING=True, NUM_OUT_BUILDINGS=4)
    assert model.uavs == uavs_in_scheduler(model)


@pytest.mark.parametrize("count", (0, 1, 2, 7))
def test_the_team_holds_exactly_the_uavs_asked_for(count, fleet):
    model = fleet(count=count)
    assert len(model.uavs) == count
    assert all(type(uav) is agents.UAV for uav in model.uavs)


def test_reset_rebuilds_the_team_without_keeping_the_old_one(fleet):
    model = fleet(count=3)
    before = list(model.uavs)

    model.reset()

    assert len(model.uavs) == 3
    assert model.uavs == uavs_in_scheduler(model)
    # the previous UAVs are gone rather than appended to
    assert not any(uav in before for uav in model.uavs)


# --- the ordering that actions rely on --------------------------------------


def test_observations_come_back_in_team_order(fleet):
    model = fleet(count=5)
    assert [observation.uav_id for observation in model.observations()] == \
           [uav.unique_id for uav in model.uavs]


def test_each_uav_gets_the_action_chosen_for_its_own_observation(fleet):
    model = fleet(count=4, policy=PerUAVPolicy())

    model.step()

    for uav in model.uavs:
        expected = PerUAVPolicy.DIRECTIONS[uav.unique_id % len(PerUAVPolicy.DIRECTIONS)]
        assert uav.selected_dir == expected, f"UAV {uav.unique_id} got another UAV's action"


def test_actions_still_line_up_after_several_steps(fleet):
    model = fleet(count=4, policy=PerUAVPolicy())

    for _ in range(5):
        model.step()

    for uav in model.uavs:
        expected = PerUAVPolicy.DIRECTIONS[uav.unique_id % len(PerUAVPolicy.DIRECTIONS)]
        assert uav.selected_dir == expected


# --- lookup by id -----------------------------------------------------------


def test_every_uav_can_be_found_by_its_id(fleet):
    model = fleet(count=5)
    for uav in model.uavs:
        assert model.uav_by_id(uav.unique_id) is uav


def test_an_unknown_id_finds_nothing(fleet):
    model = fleet(count=2)
    assert model.uav_by_id(9999) is None


# a Fire agent's id must not be mistaken for a UAV's, which the old scheduler walk guarded against
# with a type check
def test_a_non_uav_id_finds_nothing(fleet):
    model = fleet(count=2)
    assert model.uav_by_id(model.fire_list[0].unique_id) is None
