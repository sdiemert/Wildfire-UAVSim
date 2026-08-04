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


# helper that returns the positions in 'positions' ordered by how close they are to 'pos', nearest first
def by_distance(pos, positions):
    return sorted(positions, key=lambda candidate: (candidate[0] - pos[0]) ** 2 + (candidate[1] - pos[1]) ** 2)


# helper that returns the cells an action would take a UAV at 'pos' through, in the order it crosses them,
# the cell it lands on last. An action that does not move the UAV crosses nothing.
def flight_path(pos, action):
    if not action.is_movement():
        return []
    step_x, step_y = config.MOVEMENT_VECTORS[action.direction]
    return [(pos[0] + step_x * covered, pos[1] + step_y * covered)
            for covered in range(1, action.speed + 1)]


# helper that trims an action so that the UAV stops short of a cell it must not enter. Speed is given up
# one cell at a time, and the UAV holds position when even the first cell of the flight is taken.
#
# 'blocked' is the cells to keep out of: the ones other UAVs are standing on, and the ones teammates have
# already been sent to this step. Two UAVs that end a step on the same cell collide and both lose health
# points, which is what this is for; the cells of the home base are shared airspace and belong nowhere near
# 'blocked'.
def avoid(pos, action, blocked):
    if not action.is_movement() or not blocked:
        return action

    blocked = {tuple(cell) for cell in blocked}
    speed = action.speed
    for covered, cell in enumerate(flight_path(pos, action), start=1):
        if cell in blocked:
            speed = covered - 1
            break

    if speed <= 0:
        return Action.stay()
    return Action(action.direction, speed)


# helper that returns the cells within 'radius' of any of 'positions', the positions themselves included.
# It is the cushion a UAV is asked to keep around the team mates it can see: 'blocked' with a radius of
# zero is only the cells they stand on, which is the least that stops a collision, and each cell of radius
# beyond that is a cell of clear air the UAV gives up speed to preserve.
#
# Distance is counted the way the UAVs fly, so the cushion is square rather than round.
def halo(positions, radius=0):
    if radius <= 0:
        return {tuple(position) for position in positions}

    cells = set()
    for position in positions:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                cells.add((position[0] + dx, position[1] + dy))
    return cells


class Policy(ABC):
    """Decides which direction each UAV flies at a given time step, and how fast.

    Subclasses set a unique 'name', which is what the --policy command line option and the dropdown on the
    web interface use to identify them, and implement select_actions().
    """

    # identifier used by the registry, the CLI and the web interface dropdown
    name = "policy"

    # takes the parameters this policy is to be flown under, before select_actions() is called. The base
    # implementation ignores them, which is what lets every policy written before the managing system
    # existed keep working unchanged: the two parameters that matter to all of them, the speed cap and the
    # separation, are enforced by SuperPolicy after the policy has chosen, rather than being obeyed here.
    #
    # A policy that understands a setting of its own overrides this and reads it out of params.extra.
    def configure(self, params):
        return None

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
            early at the edge of the grid. Flying onto a cell another UAV holds ends the flight there and
            is a collision, which costs both of them health points, so a policy that moves its team about
            has to keep it apart: observation.uav_positions reports the UAVs in view, and avoid() above
            trims an action to stay clear of them.

            A bare direction index, or a (direction, speed) pair, is accepted as well and is coerced to an
            Action, so policies written before speeds existed keep working at one cell per step.
        """

    def __str__(self):
        return self.name
