"""Tests for the Policy interface and the registry behind --policy and the web interface dropdown.

The contract tests are parametrised over every registered policy, so a newly added policy is checked
against them automatically.

That parametrisation is also what makes these tests the evidence for the whole of specs/policies/
_contract.md: one test marked verifies("POL-GEN-...") covers every registered policy at once, and picks
up the next one without being touched.
"""

# python libraries

import inspect

import pytest

# own python modules

import config

from config import ACTION_DUMP_WATER, ACTION_STAY, N_ACTIONS

import sim.policy as policy_pkg

from sim.policy import POLICIES, REGISTERED, Action, Policy, PolicyParams, build_policy

VALID_DIRECTIONS = set(range(N_ACTIONS)) | {ACTION_STAY, ACTION_DUMP_WATER}


# --- the abstract interface -------------------------------------------------


def test_policy_cannot_be_instantiated():
    with pytest.raises(TypeError):
        Policy()


def test_subclass_without_select_actions_cannot_be_instantiated():
    class Incomplete(Policy):
        name = "incomplete"

    with pytest.raises(TypeError):
        Incomplete()


def test_subclass_implementing_the_interface_can_be_instantiated():
    class Complete(Policy):
        name = "complete"

        def select_actions(self, observations):
            return [ACTION_STAY for _ in observations]

    assert Complete().select_actions([None, None]) == [ACTION_STAY, ACTION_STAY]


# --- the registry -----------------------------------------------------------


@pytest.mark.verifies("POL-GEN-9")
def test_registry_covers_every_registered_policy():
    assert set(POLICIES) == {policy_cls.name for policy_cls in REGISTERED}


@pytest.mark.verifies("POL-GEN-6")
def test_registry_names_are_unique():
    names = [policy_cls.name for policy_cls in REGISTERED]
    assert len(names) == len(set(names))


def test_expected_policies_are_available():
    # guards against a policy silently dropping out of the dropdown after a refactor
    assert {"random", "follow-fire"} <= set(POLICIES)


@pytest.mark.verifies("POL-GEN-9")
def test_build_policy_returns_the_right_class():
    for name, policy_cls in POLICIES.items():
        assert isinstance(build_policy(name), policy_cls)


@pytest.mark.verifies("POL-GEN-9")
def test_build_policy_rejects_unknown_names():
    with pytest.raises(KeyError) as excinfo:
        build_policy("does-not-exist")
    # the message should tell the user what they can pick instead
    assert "random" in str(excinfo.value)


def test_package_exports_the_public_api():
    for name in ("Policy", "Action", "Observation", "POLICIES", "build_policy"):
        assert hasattr(policy_pkg, name)


# --- contract every policy must honour --------------------------------------


@pytest.fixture(params=[policy_cls.name for policy_cls in REGISTERED])
def any_policy(request):
    return build_policy(request.param)


def test_every_policy_is_a_policy_subclass(any_policy):
    assert isinstance(any_policy, Policy)


@pytest.mark.verifies("POL-GEN-6")
def test_every_policy_has_a_usable_name(any_policy):
    assert isinstance(any_policy.name, str) and any_policy.name
    assert str(any_policy) == any_policy.name


@pytest.mark.verifies("POL-GEN-7")
def test_a_policy_is_given_the_observations_and_nothing_else(any_policy):
    # partial observability is enforced at the signature: there is no second parameter through which a
    # policy could be handed the grid, the model or the other UAVs' internals
    parameters = list(inspect.signature(any_policy.select_actions).parameters)
    assert parameters == ["observations"], any_policy.name


@pytest.mark.verifies("POL-GEN-8")
def test_every_policy_still_runs_after_being_configured(any_policy, scenarios):
    # SuperPolicy configures every policy it holds, including the four that inherit the base
    # implementation and ignore the parameters entirely
    for params in (None, PolicyParams(), PolicyParams(speed_cap=1, separation=3)):
        any_policy.configure(params)
        assert len(any_policy.select_actions(scenarios)) == len(scenarios), any_policy.name


@pytest.mark.verifies("POL-GEN-8")
def test_every_policy_runs_without_ever_being_configured(any_policy, scenarios):
    # --policy and the tests both build a policy and call it directly, without going through SuperPolicy
    assert len(any_policy.select_actions(scenarios)) == len(scenarios), any_policy.name


@pytest.mark.verifies("POL-GEN-1")
def test_every_policy_returns_one_action_per_uav(any_policy, observation):
    observations = [observation(pos=(5, 5), burning=[(6, 6)], uav_id=i) for i in range(4)]
    assert len(any_policy.select_actions(observations)) == len(observations)


@pytest.fixture
def scenarios(observation):
    return [
        observation(pos=(5, 5)),                                  # sees nothing
        observation(pos=(5, 5), unburnt=[(4, 5), (6, 5)]),        # sees only vegetation
        observation(pos=(5, 5), burning=[(6, 5)]),                # sees fire
        observation(pos=(5, 5), burning=[(5, 5)]),                # is over the fire
    ]


@pytest.mark.verifies("POL-GEN-2")
def test_every_policy_returns_valid_actions(any_policy, scenarios):
    actions = any_policy.select_actions(scenarios)
    assert all(isinstance(action, Action) for action in actions)
    assert {action.direction for action in actions} <= VALID_DIRECTIONS


@pytest.mark.verifies("POL-GEN-3")
def test_no_policy_asks_for_more_speed_than_a_uav_has(any_policy, scenarios, uav_speed):
    # a policy may not know how fast a UAV is, but none of the ones shipped here overshoots it
    for speed in (0, 1, 3):
        uav_speed(speed)
        actions = any_policy.select_actions(scenarios)
        assert all(0 <= action.speed <= speed for action in actions), any_policy.name


@pytest.mark.verifies("POL-GEN-4")
def test_actions_that_do_not_move_carry_no_speed(any_policy, scenarios):
    for action in any_policy.select_actions(scenarios):
        if action.direction in (ACTION_STAY, ACTION_DUMP_WATER):
            assert action.speed == 0


@pytest.mark.verifies("POL-GEN-5")
def test_every_policy_handles_no_uavs(any_policy):
    assert any_policy.select_actions([]) == []


# --- the Action a policy returns --------------------------------------------


@pytest.mark.verifies("POL-GEN-2")
def test_a_bare_direction_is_still_accepted():
    # policies written before speeds existed return a plain action index, which means one cell per step
    assert Action.coerce(config.ACTION_UP) == Action(config.ACTION_UP, 1)


@pytest.mark.verifies("POL-GEN-4")
def test_a_bare_direction_that_does_not_move_carries_no_speed():
    assert Action.coerce(ACTION_STAY) == Action(ACTION_STAY, 0)
    assert Action.coerce(ACTION_DUMP_WATER) == Action(ACTION_DUMP_WATER, 0)


@pytest.mark.verifies("POL-GEN-2")
def test_a_direction_and_speed_pair_is_accepted():
    assert Action.coerce((config.ACTION_LEFT, 4)) == Action(config.ACTION_LEFT, 4)


def test_an_action_is_left_alone():
    action = Action(config.ACTION_DOWN, 2)
    assert Action.coerce(action) is action


def test_a_malformed_pair_is_rejected():
    with pytest.raises(ValueError, match="direction, speed"):
        Action.coerce((config.ACTION_DOWN, 2, 7))


def test_actions_describe_themselves_for_the_log():
    assert str(Action(config.ACTION_UP, 3)) == "up at speed 3"
    assert str(Action.stay()) == "stay"
    assert str(Action.dump()) == "dump water"
