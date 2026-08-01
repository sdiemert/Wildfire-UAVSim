"""Uniform random policy: the original behaviour of the simulator."""

# own python modules

# imported as a module, not with 'from config import *', so that SYSTEM_RANDOM and N_ACTIONS are looked up
# when they are used. A runner that seeds or overrides them (see headless.py) then affects this policy too.
import config

from .base import Policy


class RandomPolicy(Policy):
    """Every UAV picks uniformly among the movement actions, ignoring what it sees."""

    name = "random"

    def select_actions(self, observations):
        return [config.SYSTEM_RANDOM.choice(range(0, config.N_ACTIONS)) for _ in observations]
