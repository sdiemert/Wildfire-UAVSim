"""Uniform random policy: the original behaviour of the simulator."""

# own python modules

# imported as a module, not with 'from config import *', so that SYSTEM_RANDOM and N_ACTIONS are looked up
# when they are used. A runner that seeds or overrides them (see headless.py) then affects this policy too.
import config

from .action import Action
from .base import Policy


class RandomPolicy(Policy):
    """Every UAV picks uniformly among the movement actions, ignoring what it sees.

    The speed is drawn uniformly too, between one cell and UAV_SPEED, which keeps the baseline as
    uninformed about speed as it is about direction.
    """

    name = "random"

    def select_actions(self, observations):
        return [self.action_for(observation) for observation in observations]

    # decides the action for a single UAV
    def action_for(self, observation):
        direction = config.SYSTEM_RANDOM.choice(range(0, config.N_ACTIONS))
        # a UAV that cannot fly at all still has to be given an action
        if config.UAV_SPEED < 1:
            return Action(direction, 0)
        return Action(direction, config.SYSTEM_RANDOM.randint(1, config.UAV_SPEED))
