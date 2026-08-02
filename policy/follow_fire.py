"""Toy policy that flies toward the nearest visible fire."""

# own python modules

from config import ACTION_STAY

from .base import Policy, nearest, step_towards


class FollowFirePolicy(Policy):
    """Fly one cell toward the nearest visible fire, hold position when no fire is in view.

    Only the observed cells are consulted, so a UAV with no fire inside its UAV_OBSERVATION_RADIUS window
    stays put rather than searching. Movement is one cell per step along a single axis, so the UAV
    approaches diagonal targets in a staircase.

    Note that targeting the *nearest* burning cell makes a UAV settle on the inner edge of a fire and then
    sit in the burnt out core, which scores worse on MR1 than the random policy on a dense grid.
    """

    name = "follow-fire"

    def select_actions(self, observations):
        return [self.action_for(observation) for observation in observations]

    # decides the action for a single UAV
    def action_for(self, observation):
        # nearest burning cell in view, by squared Euclidean distance
        target = nearest(observation.pos, observation.burning_positions())
        if target is None:  # nothing visible, hold position
            return ACTION_STAY
        # step_towards() returns ACTION_STAY when the UAV is already above the fire
        return step_towards(observation.pos, target)
