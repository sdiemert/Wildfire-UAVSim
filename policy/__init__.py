"""UAV policies.

A policy receives one Observation per UAV, describing only what that UAV can see, and returns one action per
UAV. WildFireModel calls it once per time step, in step().

To add your own policy:

  1. create policy/my_policy.py with a Policy subclass that has a unique 'name' and implements
     select_actions(observations)
  2. import it below and add the class to the REGISTERED tuple

It is then available as `python3 headless.py --policy my-policy`, and appears in the dropdown on the web
interface without any further change.
"""

# own python modules

from .base import Policy
from .observation import Observation
from .follow_fire import FollowFirePolicy
from .random_policy import RandomPolicy

# every policy the simulator knows about
REGISTERED = (
    RandomPolicy,
    FollowFirePolicy,
)

# name -> class, used by the --policy option and the web interface dropdown
POLICIES = {policy_cls.name: policy_cls for policy_cls in REGISTERED}


# builds a policy by name, raising a helpful error for unknown ones
def build_policy(name):
    if name not in POLICIES:
        raise KeyError(f"unknown policy {name!r}, available: {', '.join(sorted(POLICIES))}")
    return POLICIES[name]()


__all__ = ["Policy", "Observation", "RandomPolicy", "FollowFirePolicy", "POLICIES", "REGISTERED",
           "build_policy"]
