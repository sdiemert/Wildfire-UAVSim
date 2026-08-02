"""Tests for the Policy interface and the registry behind --policy and the web interface dropdown.

The contract tests are parametrised over every registered policy, so a newly added policy is checked
against them automatically.
"""

# python libraries

import pytest

# own python modules

from config import ACTION_STAY, N_ACTIONS

import policy as policy_pkg

from policy import POLICIES, REGISTERED, Policy, build_policy

VALID_ACTIONS = set(range(N_ACTIONS)) | {ACTION_STAY}


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


def test_registry_covers_every_registered_policy():
    assert set(POLICIES) == {policy_cls.name for policy_cls in REGISTERED}


def test_registry_names_are_unique():
    names = [policy_cls.name for policy_cls in REGISTERED]
    assert len(names) == len(set(names))


def test_expected_policies_are_available():
    # guards against a policy silently dropping out of the dropdown after a refactor
    assert {"random", "follow-fire"} <= set(POLICIES)


def test_build_policy_returns_the_right_class():
    for name, policy_cls in POLICIES.items():
        assert isinstance(build_policy(name), policy_cls)


def test_build_policy_rejects_unknown_names():
    with pytest.raises(KeyError) as excinfo:
        build_policy("does-not-exist")
    # the message should tell the user what they can pick instead
    assert "random" in str(excinfo.value)


def test_package_exports_the_public_api():
    for name in ("Policy", "Observation", "POLICIES", "build_policy"):
        assert hasattr(policy_pkg, name)


# --- contract every policy must honour --------------------------------------


@pytest.fixture(params=[policy_cls.name for policy_cls in REGISTERED])
def any_policy(request):
    return build_policy(request.param)


def test_every_policy_is_a_policy_subclass(any_policy):
    assert isinstance(any_policy, Policy)


def test_every_policy_has_a_usable_name(any_policy):
    assert isinstance(any_policy.name, str) and any_policy.name
    assert str(any_policy) == any_policy.name


def test_every_policy_returns_one_action_per_uav(any_policy, observation):
    observations = [observation(pos=(5, 5), burning=[(6, 6)], uav_id=i) for i in range(4)]
    assert len(any_policy.select_actions(observations)) == len(observations)


def test_every_policy_returns_valid_actions(any_policy, observation):
    scenarios = [
        observation(pos=(5, 5)),                                  # sees nothing
        observation(pos=(5, 5), unburnt=[(4, 5), (6, 5)]),        # sees only vegetation
        observation(pos=(5, 5), burning=[(6, 5)]),                # sees fire
        observation(pos=(5, 5), burning=[(5, 5)]),                # is over the fire
    ]
    assert set(any_policy.select_actions(scenarios)) <= VALID_ACTIONS


def test_every_policy_handles_no_uavs(any_policy):
    assert any_policy.select_actions([]) == []
