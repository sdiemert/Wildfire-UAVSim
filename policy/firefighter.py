"""Policy for the firefighting extension: attack the fire with water, refill at the base."""

# own python modules

# see the note in random_policy.py about importing config as a module
import config

from .action import Action
from .base import Policy, nearest, step_towards


class FirefighterPolicy(Policy):
    """Carry water to the fire, dump it, then go back to the base for more.

    Each UAV follows the same simple loop:

      * carrying water, with fire close enough for the drop to reach it -> dump the water
      * carrying water, with fire in view but out of reach          -> fly toward the nearest fire
      * carrying water, with a threatened out building in view       -> defend it
      * empty                                                        -> fly back to the base and refill

    Refilling is not an action: standing on the base with an empty tank is enough, and the base serves one
    UAV at a time, so UAVs that arrive together queue up.

    This policy only makes sense with ACTIVATE_FIREFIGHTING switched on. Without it no UAV ever carries
    water, and it degenerates into flying to the base and holding position there.
    """

    name = "firefighter"

    def select_actions(self, observations):
        return [self.action_for(observation) for observation in observations]

    # decides the action for a single UAV
    def action_for(self, observation):
        if not observation.has_water:
            return self.return_to_base(observation)

        burning = observation.burning_positions()
        target = nearest(observation.pos, burning)
        if target is None:  # nothing to put out in view
            return Action.stay()

        # a building already on fire, or a fire next to one, is worth more than open vegetation
        threatened = self.threatened_building(observation, burning)
        if threatened is not None:
            target = threatened

        if self.within_drop_range(observation.pos, target):
            return Action.dump()
        return step_towards(observation.pos, target)

    # flies back to the home base, where refilling happens by itself
    def return_to_base(self, observation):
        if observation.base_pos is None or observation.at_base():
            # already there, or the extension is off and there is no base to go to
            return Action.stay()
        return step_towards(observation.pos, observation.base_pos)

    # checks whether the drop would reach the target from the given position
    def within_drop_range(self, pos, target):
        distance_squared = (target[0] - pos[0]) ** 2 + (target[1] - pos[1]) ** 2
        return distance_squared <= config.WATER_DROP_RADIUS ** 2

    # returns the burning cell closest to an out building in view, when one is burning or about to, so that
    # the UAV defends the buildings before it defends open vegetation
    def threatened_building(self, observation, burning):
        if not observation.building_positions:
            return None

        at_risk = []
        for building in observation.building_positions:
            fire = nearest(building, burning)
            if fire is None:
                continue
            distance_squared = (fire[0] - building[0]) ** 2 + (fire[1] - building[1]) ** 2
            if distance_squared <= config.WATER_DROP_RADIUS ** 2:
                at_risk.append(fire)

        return nearest(observation.pos, at_risk)
