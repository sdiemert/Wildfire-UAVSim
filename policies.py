"""Policies that decide which direction each UAV flies at every time step.

A policy receives one Observation per UAV, describing only what that UAV can actually see, and returns one
action per UAV. The model calls it once per step, in WildFireModel.step().

To add your own policy:

    class MyPolicy(Policy):
        def select_actions(self, observations):
            return [ACTION_STAY for _ in observations]

    POLICIES["my-policy"] = MyPolicy

and select it with `python3 headless.py --policy my-policy`.

The returned list must be ordered exactly like `observations`, which follows scheduler order; the model
hands directions to the UAVs in that same order (see WildFireModel.set_drone_dirs).
"""

# python libraries

from dataclasses import dataclass, field

# own python modules

from config import *


# ---------------------------------------------------------------------------
# what a UAV can see
# ---------------------------------------------------------------------------


@dataclass
class Observation:
    """One UAV's partial view of the grid, as produced by UAV.observe().

    'cells' holds (position, burning) for every observed cell that contains vegetation. Cells without a Fire
    agent are absent, which is why flat_states() can be shorter than N_OBSERVATIONS near the grid edges.
    """

    uav_id: int
    pos: tuple
    cells: list = field(default_factory=list)

    # positions of the cells that are on fire right now
    def burning_positions(self):
        return [position for position, burning in self.cells if burning]

    # the flat 0/1 list the rest of the model already expects, in observation order
    def flat_states(self):
        return [burning for _, burning in self.cells]

    # number of burning cells in view
    def burning_count(self):
        return sum(burning for _, burning in self.cells)


# ---------------------------------------------------------------------------
# policies
# ---------------------------------------------------------------------------


class Policy:
    """Base class. Subclasses turn observations into one action per UAV."""

    name = "policy"

    def select_actions(self, observations):
        raise NotImplementedError

    def __str__(self):
        return self.name


class RandomPolicy(Policy):
    """The original behaviour: every UAV picks uniformly among the movement actions, ignoring what it sees."""

    name = "random"

    def select_actions(self, observations):
        return [SYSTEM_RANDOM.choice(range(0, N_ACTIONS)) for _ in observations]


class FollowFirePolicy(Policy):
    """Toy policy: fly one cell toward the nearest visible fire, hold position when no fire is in view.

    Only the observed cells are consulted, so a UAV with no fire inside its UAV_OBSERVATION_RADIUS window
    stays put rather than searching. Movement is one cell per step along a single axis, so the UAV
    approaches diagonal targets in a staircase.
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
        prefer_x = abs(dx) > abs(dy) or (abs(dx) == abs(dy) and SYSTEM_RANDOM.random() < 0.5)
        if prefer_x:
            return ACTION_RIGHT if dx > 0 else ACTION_LEFT
        return ACTION_UP if dy > 0 else ACTION_DOWN


# registry used by the --policy command line option
POLICIES = {
    RandomPolicy.name: RandomPolicy,
    FollowFirePolicy.name: FollowFirePolicy,
}


# builds a policy by name, raising a helpful error for unknown ones
def build_policy(name):
    if name not in POLICIES:
        raise KeyError(f"unknown policy {name!r}, available: {', '.join(sorted(POLICIES))}")
    return POLICIES[name]()
