"""Policy for the firefighting extension: attack the fire with water, refill at the base."""

# own python modules

# see the note in random_policy.py about importing config as a module
import config

from .action import Action
from .base import Policy, avoid, by_distance, flight_path, nearest, step_towards


class FirefighterPolicy(Policy):
    """Carry water to the fire, dump it, then go back to the base for more.

    Each UAV follows the same simple loop:

      * carrying water, with fire close enough for the drop to reach it -> dump the water
      * carrying water, with fire in view but out of reach          -> fly toward the nearest fire
      * carrying water, with a threatened out building in view       -> defend it
      * empty                                                        -> fly back to the base and refill

    Refilling is not an action: standing on the base with an empty tank is enough, and the base serves one
    UAV at a time, so UAVs that arrive together queue up.

    The team is kept apart, because UAVs that end a step on the same cell collide and lose health points.
    Two rules do it, and both need the whole team, which is why the work is in select_actions() rather than
    in action_for():

      * no two UAVs are sent to the same fire in one step. Targets are claimed in team order, and a UAV
        whose nearest fire is already taken moves on to the next one it can see. Dropping water twice on
        one cell would be wasted anyway.
      * an action is trimmed so that the UAV neither flies into a UAV it can see nor lands where a teammate
        has already been sent. It gives up speed one cell at a time, and holds position when there is no
        room at all. The home base is exempt: any number of UAVs may sit on it, which is what lets them
        queue there to refill.

    This policy only makes sense with ACTIVATE_FIREFIGHTING switched on. Without it no UAV ever carries
    water, and it degenerates into flying to the base and holding position there.
    """

    name = "firefighter"

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

            action = self.deconflict(observation, action, reserved)
            reserved.update(flight_path(observation.pos, action))
            actions.append(action)
        return actions

    # decides the action for a single UAV, and reports the fire it went for so that the rest of the team
    # leaves that one alone. 'claimed' is the fires the UAVs before it in the team were sent to.
    def action_for(self, observation, claimed=()):
        if not observation.has_water:
            # the base is shared airspace, so going home claims nothing
            return self.return_to_base(observation), None

        burning = observation.burning_positions()
        target = self.pick_target(observation, burning, claimed)
        if target is None:  # nothing left to put out that a teammate is not already handling
            return Action.stay(), None

        if self.within_drop_range(observation.pos, target):
            return Action.dump(), target
        return step_towards(observation.pos, target), target

    # chooses which fire this UAV attacks: the nearest one that no teammate has claimed this step, unless a
    # threatened out building offers an unclaimed fire, which is worth more than open vegetation
    def pick_target(self, observation, burning, claimed):
        claimed = {tuple(cell) for cell in claimed}

        for candidates in (self.threatened_fires(observation, burning), burning):
            for candidate in by_distance(observation.pos, candidates):
                if tuple(candidate) not in claimed:
                    return candidate
        return None

    # flies back to the home base, where refilling happens by itself
    def return_to_base(self, observation):
        if observation.base_pos is None or observation.at_base():
            # already there, or the extension is off and there is no base to go to
            return Action.stay()
        return step_towards(observation.pos, observation.base_pos)

    # trims an action so that the UAV stops short of a cell another UAV is standing on, and short of one a
    # teammate has already been sent through this step. Cells of the home base are left out of it: UAVs do
    # not collide there, and avoiding them would leave a UAV circling its own base instead of refilling.
    def deconflict(self, observation, action, reserved):
        shared = set(observation.base_footprint())
        blocked = ({tuple(cell) for cell in observation.uav_positions} | reserved) - shared
        return avoid(observation.pos, action, blocked)

    # checks whether the drop would reach the target from the given position
    def within_drop_range(self, pos, target):
        distance_squared = (target[0] - pos[0]) ** 2 + (target[1] - pos[1]) ** 2
        return distance_squared <= config.WATER_DROP_RADIUS ** 2

    # returns the burning cells that are on, or right next to, an out building in view, so that the UAV
    # defends the buildings before it defends open vegetation
    def threatened_fires(self, observation, burning):
        if not observation.building_positions:
            return []

        at_risk = []
        for building in observation.building_positions:
            fire = nearest(building, burning)
            if fire is None:
                continue
            distance_squared = (fire[0] - building[0]) ** 2 + (fire[1] - building[1]) ** 2
            if distance_squared <= config.WATER_DROP_RADIUS ** 2:
                at_risk.append(fire)

        return at_risk
