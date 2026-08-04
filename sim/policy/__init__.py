"""UAV policies.

A policy receives one Observation per UAV, describing only what that UAV can see, and returns one Action per
UAV: a direction and a speed, for example Action(ACTION_UP, 3) to fly three cells north. WildFireModel calls
it once per time step, in step().

To add your own policy:

  1. create sim/policy/my_policy.py with a Policy subclass that has a unique 'name' and implements
     select_actions(observations)
  2. import it below and add the class to the REGISTERED tuple

It is then available as `python3 headless.py --policy my-policy`, and appears in the dropdown on the web
interface without any further change.
"""

# own python modules

from .action import Action
from .base import Policy, avoid, by_distance, flight_path, halo, nearest, step_towards
from .observation import Observation
from .params import PolicyParams
from .defend_base import DefendBasePolicy
from .disperse import DispersePolicy
from .firefighter import FirefighterPolicy
from .follow_fire import FollowFirePolicy
from .random_policy import RandomPolicy

# every policy the simulator knows about, and every policy the managing system may allocate to a UAV
REGISTERED = (
    RandomPolicy,
    FollowFirePolicy,
    FirefighterPolicy,
    DefendBasePolicy,
    DispersePolicy,
)

# name -> class, used by the --policy option and the web interface dropdown
POLICIES = {policy_cls.name: policy_cls for policy_cls in REGISTERED}


# builds a policy by name, raising a helpful error for unknown ones
def build_policy(name):
    if name not in POLICIES:
        raise KeyError(f"unknown policy {name!r}, available: {', '.join(sorted(POLICIES))}")
    return POLICIES[name]()


# imported last, because SuperPolicy builds the policies above through build_policy() and so needs this
# module to be most of the way through importing before it can be defined
from .super_policy import SuperPolicy

__all__ = ["Action", "Policy", "Observation", "PolicyParams", "RandomPolicy", "FollowFirePolicy",
           "FirefighterPolicy", "DefendBasePolicy", "DispersePolicy", "SuperPolicy",
           "POLICIES", "REGISTERED", "build_policy", "avoid", "by_distance", "flight_path", "halo",
           "nearest", "step_towards"]
