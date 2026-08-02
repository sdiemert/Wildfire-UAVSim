"""Abstract interface that every UAV policy implements."""

# python libraries

from abc import ABC, abstractmethod

# own python modules

# see the note in random_policy.py about importing config as a module
import config

from config import ACTION_DOWN, ACTION_LEFT, ACTION_RIGHT, ACTION_STAY, ACTION_UP


# helper shared by the policies that home in on something: returns the action that takes a UAV at 'pos' one
# cell closer to 'target', closing the larger gap first and breaking a diagonal tie randomly. Returns
# ACTION_STAY when the UAV is already there.
def step_towards(pos, target):
    dx = target[0] - pos[0]
    dy = target[1] - pos[1]

    if dx == 0 and dy == 0:
        return ACTION_STAY

    prefer_x = abs(dx) > abs(dy) or (abs(dx) == abs(dy) and config.SYSTEM_RANDOM.random() < 0.5)
    if prefer_x:
        return ACTION_RIGHT if dx > 0 else ACTION_LEFT
    return ACTION_UP if dy > 0 else ACTION_DOWN


# helper that returns the position in 'positions' closest to 'pos', or None when there are none
def nearest(pos, positions):
    if not positions:
        return None
    return min(positions, key=lambda candidate: (candidate[0] - pos[0]) ** 2 + (candidate[1] - pos[1]) ** 2)


class Policy(ABC):
    """Decides which direction each UAV flies at a given time step.

    Subclasses set a unique 'name', which is what the --policy command line option and the dropdown on the
    web interface use to identify them, and implement select_actions().
    """

    # identifier used by the registry, the CLI and the web interface dropdown
    name = "policy"

    @abstractmethod
    def select_actions(self, observations):
        """Return one action per UAV, ordered exactly like 'observations'.

        Args:
            observations: list of Observation, one per UAV, in scheduler order. Each one describes only
                what that UAV can see, so a policy cannot cheat by reading the whole grid.

        Returns:
            list of action indices. Movement actions are ACTION_RIGHT, ACTION_DOWN, ACTION_LEFT and
            ACTION_UP; ACTION_STAY holds the current position. All are defined in config.py.
        """

    def __str__(self):
        return self.name
