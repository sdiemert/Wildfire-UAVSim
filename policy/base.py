"""Abstract interface that every UAV policy implements."""

# python libraries

from abc import ABC, abstractmethod

# own python modules

# see the note in random_policy.py about importing config as a module
import config

from config import ACTION_DOWN, ACTION_LEFT, ACTION_RIGHT, ACTION_UP

from .action import Action


# helper shared by the policies that home in on something: returns the action that takes a UAV at 'pos'
# toward 'target', closing the larger gap first and breaking a diagonal tie randomly. The speed is how far
# the target is along the chosen axis, so the UAV closes the whole gap in one step when it can and never
# overshoots, capped by how fast a UAV can fly. 'speed' overrides that cap for a policy that wants to
# approach more carefully. Returns Action.stay() when the UAV is already there.
def step_towards(pos, target, speed=None):
    dx = target[0] - pos[0]
    dy = target[1] - pos[1]

    if dx == 0 and dy == 0:
        return Action.stay()

    prefer_x = abs(dx) > abs(dy) or (abs(dx) == abs(dy) and config.SYSTEM_RANDOM.random() < 0.5)
    if prefer_x:
        direction = ACTION_RIGHT if dx > 0 else ACTION_LEFT
        distance = abs(dx)
    else:
        direction = ACTION_UP if dy > 0 else ACTION_DOWN
        distance = abs(dy)

    limit = config.UAV_SPEED if speed is None else speed
    return Action(direction, min(distance, limit))


# helper that returns the position in 'positions' closest to 'pos', or None when there are none
def nearest(pos, positions):
    if not positions:
        return None
    return min(positions, key=lambda candidate: (candidate[0] - pos[0]) ** 2 + (candidate[1] - pos[1]) ** 2)


class Policy(ABC):
    """Decides which direction each UAV flies at a given time step, and how fast.

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
            list of Action, each giving a direction and a speed, for example
            Action(ACTION_UP, 3) to fly three cells north. Movement directions are ACTION_RIGHT,
            ACTION_DOWN, ACTION_LEFT and ACTION_UP; Action.stay() holds the current position and
            Action.dump() drops water. All the constants are defined in config.py.

            A UAV never covers more than UAV_SPEED cells per step, whatever speed is asked for, and stops
            early at the edge of the grid or in front of another UAV.

            A bare direction index, or a (direction, speed) pair, is accepted as well and is coerced to an
            Action, so policies written before speeds existed keep working at one cell per step.
        """

    def __str__(self):
        return self.name
