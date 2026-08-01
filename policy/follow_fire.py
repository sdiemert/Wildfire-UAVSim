"""Toy policy that flies toward the nearest visible fire."""

# own python modules

# see the note in random_policy.py about importing config as a module
import config

from config import ACTION_DOWN, ACTION_LEFT, ACTION_RIGHT, ACTION_STAY, ACTION_UP

from .base import Policy


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
        burning = observation.burning_positions()
        if not burning:  # nothing visible, hold position
            return ACTION_STAY

        x, y = observation.pos
        # nearest burning cell, by squared Euclidean distance (no need for the square root to rank)
        target = min(burning, key=lambda position: (position[0] - x) ** 2 + (position[1] - y) ** 2)
        dx = target[0] - x
        dy = target[1] - y

        if dx == 0 and dy == 0:  # already above the fire, stay and keep watching it
            return ACTION_STAY

        # close the larger gap first; break ties randomly so UAVs don't all bias the same way
        prefer_x = abs(dx) > abs(dy) or (abs(dx) == abs(dy) and config.SYSTEM_RANDOM.random() < 0.5)
        if prefer_x:
            return ACTION_RIGHT if dx > 0 else ACTION_LEFT
        return ACTION_UP if dy > 0 else ACTION_DOWN
