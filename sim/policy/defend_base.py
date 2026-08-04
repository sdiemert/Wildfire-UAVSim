"""Policy that puts the home base first: intercept whatever fire is closest to it."""

# own python modules

# see the note in random_policy.py about importing config as a module
import config

from .action import Action
from .base import Policy, by_distance, flight_path, nearest, step_towards


class DefendBasePolicy(Policy):
    """Attack the fire that most threatens the home base, rather than the fire nearest the UAV.

    `firefighter` sends each UAV at whatever is burning closest to it, which is the right thing to do when
    the goal is to put the wildfire out and the wrong thing to do when the goal is to keep one building
    standing: a team spread over the map fights the fire it happens to be standing over while the front
    that matters walks into the base.

    This policy sorts the fire it can see by how close it is *to the base*, and ignores anything further
    from the base than BASE_THREAT_RADIUS. So a UAV holding station over the base and a UAV out on the
    perimeter both converge on the same front, from wherever they happen to be.

    The loop is otherwise the firefighting one:

      * down to the fuel reserve                            -> break off for home and wait for a full tank
      * empty of water                                      -> back to the base to refill
      * fire in view threatening the base, within drop range -> dump
      * fire in view threatening the base, further off       -> fly at it
      * nothing threatening the base in view                 -> hold station over the base

    Holding station over the base rather than wandering is deliberate. The base is shared airspace, so any
    number of UAVs may wait there without colliding, and a UAV waiting there is already where it needs to
    be when the front arrives. It also means this policy costs nothing in collisions, which is what makes
    it safe for the managing system to allocate freely.

    Like `firefighter`, this only makes sense with ACTIVATE_FIREFIGHTING switched on; without a base there
    is nothing to defend and every UAV simply holds position.
    """

    name = "defend-base"

    def select_actions(self, observations):
        # the fires this team has already been sent to, and the cells it has already been sent through, so
        # that no two UAVs are given the same target or the same piece of airspace in one step
        claimed = set()
        reserved = set()

        actions = []
        for observation in observations:
            action, target = self.action_for(observation, claimed)
            if target is not None:
                claimed.add(tuple(target))
            reserved.update(flight_path(observation.pos, action))
            actions.append(action)
        return actions

    # decides the action for a single UAV, and reports the fire it went for so that the rest of the team
    # leaves that one alone. SuperPolicy trims the result for traffic afterwards, which is why there is no
    # deconfliction here; the reserved cells are still tracked so that this policy is correct when it is
    # used on its own through --policy defend-base.
    def action_for(self, observation, claimed=()):
        # an empty tank costs a UAV every health point it has, so the reserve outranks the defending, the
        # same way it does in firefighter
        if observation.low_fuel() or not observation.has_water:
            return self.hold_at_base(observation), None

        target = self.pick_target(observation, claimed)
        if target is None:  # nothing worth defending against in view
            return self.hold_at_base(observation), None

        if self.within_drop_range(observation.pos, target):
            return Action.dump(), target
        return step_towards(observation.pos, target), target

    # chooses which fire this UAV attacks: of the burning cells in view that are close enough to the base
    # to threaten it, the one closest to the base that no team mate has claimed this step
    def pick_target(self, observation, claimed=()):
        base = self.base_anchor(observation)
        if base is None:  # no base to defend, so nothing threatens it
            return None

        claimed = {tuple(cell) for cell in claimed}
        threatening = [cell for cell in observation.burning_positions()
                       if self.distance_to_base(cell, observation) <= config.BASE_THREAT_RADIUS]

        # ordered by how close each one is to the base, nearest the base first, which is what makes the
        # whole team converge on one front instead of each UAV picking off what is under it
        for candidate in by_distance(base, threatening):
            if tuple(candidate) not in claimed:
                return candidate
        return None

    # how far a cell is from the base footprint, counted from the nearest cell of it the UAV knows about
    def distance_to_base(self, cell, observation):
        footprint = observation.base_footprint()
        if not footprint:
            return float("inf")
        closest = nearest(cell, footprint)
        return ((closest[0] - cell[0]) ** 2 + (closest[1] - cell[1]) ** 2) ** 0.5

    # the cell this UAV treats as the base: the anchor it was told about, or the nearest cell of the
    # footprint when it knows the whole thing
    def base_anchor(self, observation):
        footprint = observation.base_footprint()
        if not footprint:
            return None
        return nearest(observation.pos, footprint)

    # flies back to the base and waits there. Refilling and refuelling both happen by themselves once the
    # UAV is standing on it, and the base is shared airspace, so a whole team may wait together.
    def hold_at_base(self, observation):
        base = self.base_anchor(observation)
        if base is None or observation.at_base():
            return Action.stay()
        return step_towards(observation.pos, base)

    # checks whether the drop would reach the target from the given position
    def within_drop_range(self, pos, target):
        distance_squared = (target[0] - pos[0]) ** 2 + (target[1] - pos[1]) ** 2
        return distance_squared <= config.WATER_DROP_RADIUS ** 2
