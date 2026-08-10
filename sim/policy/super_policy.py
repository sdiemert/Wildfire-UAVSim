"""The policy that flies a team under several policies at once.

SuperPolicy is what makes a per UAV allocation possible without the model knowing anything about it. It
implements the ordinary Policy interface, so WildFireModel holds it and calls select_actions() exactly as
it calls any other policy; behind that it keeps a table of which basic policy, and which parameters, each
UAV has been allocated, and routes the observations accordingly.

It is part of the *managed* system. The managing system never calls it directly: it writes into the table
through AllocationEffector (see sim/adapters.py), which is the effector end of the sensor/effector contract.

Two jobs, in order:

  1. **dispatch.** The UAVs are grouped by the policy and parameters they were allocated, and each group is
     handed to its policy in one call. Grouping rather than asking each policy for one UAV at a time is what
     preserves the team level reasoning the basic policies already do: FirefighterPolicy claims each fire so
     that no two of its UAVs are sent to the same one, and it can only do that if it is shown its whole
     group at once.

  2. **traffic.** Once every UAV has an action, they are trimmed against each other, in team order: a UAV
     gives up speed rather than end its step on a cell another UAV holds or has been sent to.

Step 2 is new, and is a strict improvement on what the basic policies do alone. FirefighterPolicy
deconflicts its own team, but it has no way of knowing about a UAV flying `defend-base` on the next cell,
because that UAV was never in its call. A mixed allocation without a fleet wide pass would collide far more
than either policy does on its own, which would make the managing system's second goal harder rather than
easier. Doing it here, once, over the whole team, is the only place it can be done correctly.
"""

# own python modules

# see the note in random_policy.py about importing config as a module
import config

from .action import Action
from .base import Policy, avoid, flight_path, halo
from .params import PolicyParams


class SuperPolicy(Policy):
    """Flies each UAV under the policy it has been allocated, and keeps the whole team apart.

    The table is keyed by UAV unique id and holds (policy name, PolicyParams). A UAV that has never been
    allocated anything flies the default it was built with, which is what covers the first step of a run,
    before the managing system has evaluated anything, and any UAV a planner forgets about.

    This policy is deliberately *not* in the registry: it cannot be selected with --policy, because on its
    own it would only ever fly the default and there would be no point. It is built by AdaptiveWildFireModel
    when MANAGING_SYSTEM is 'local' or 'remote'.
    """

    name = "super"

    # constructor. 'default' names the policy an unallocated UAV flies; 'build' is how a policy name is
    # turned into an instance, injected so that this module does not have to import the registry it is
    # itself listed from.
    def __init__(self, default=None, default_params=None, build=None):
        # imported here rather than at module scope: sim/policy/__init__.py imports this module to export
        # it, so importing the registry from the top of this file would be a cycle
        from . import build_policy

        self.build = build if build is not None else build_policy
        self.default = default if default is not None else config.DEFAULT_UAV_POLICY
        self.default_params = default_params if default_params is not None else PolicyParams()
        # uav id -> (policy name, PolicyParams)
        self.table = {}
        # (policy name, params key) -> policy instance. Policies hold no state between steps, so one
        # instance serves every UAV allocated the same policy under the same parameters.
        self.instances = {}
        # how many times the table has actually changed, which the status panel reports
        self.assignments = 0

        # fails here rather than on the first step if the configured default does not exist
        self.build(self.default)

    # allocates a policy and its parameters to one UAV. This is what the effector calls, and the only way
    # the table is ever written. Returns True when it changed anything, so that a caller can tell a real
    # adaptation from a planner repeating itself.
    def assign(self, uav_id, policy_name, params=None):
        params = PolicyParams() if params is None else params
        current = self.table.get(uav_id)
        if current is not None and current[0] == policy_name and current[1] == params:
            return False

        self.table[uav_id] = (policy_name, params)
        self.assignments += 1
        return True

    # what every UAV is currently flying, as {uav id: (policy name, PolicyParams)}. This is what the sensor
    # reads, so that the managing system is told what it decided last time as well as what came of it.
    def assignment(self):
        return dict(self.table)

    # what one UAV is flying, falling back to the default for one that has never been allocated anything
    def allocated(self, uav_id):
        return self.table.get(uav_id, (self.default, self.default_params))

    # the policy instance for a name and parameters, built once and reused
    def instance_for(self, policy_name, params):
        key = (policy_name, params.key())
        if key not in self.instances:
            self.instances[key] = self.build(policy_name)
        return self.instances[key]

    def select_actions(self, observations):
        if not observations:
            return []

        # --- dispatch: one call per (policy, parameters) group, so that a policy which reasons about its
        # whole team still sees all of the UAVs it is responsible for
        groups = {}
        for index, observation in enumerate(observations):
            policy_name, params = self.allocated(observation.uav_id)
            groups.setdefault((policy_name, params.key()), (policy_name, params, [], []))
            _, _, indices, group = groups[(policy_name, params.key())]
            indices.append(index)
            group.append(observation)

        actions = [None] * len(observations)
        for policy_name, params, indices, group in groups.values():
            policy = self.instance_for(policy_name, params)
            policy.configure(params)
            chosen = policy.select_actions(group)
            # a policy is contracted to return one action per observation; anything else is its bug, and
            # is reported against the policy that did it rather than as a confusing IndexError below
            if len(chosen) != len(group):
                raise ValueError(f"policy {policy_name!r} returned {len(chosen)} actions "
                                 f"for {len(group)} UAV(s)")
            for index, action in zip(indices, chosen):
                actions[index] = Action.coerce(action)

        # --- traffic: trim the whole team against itself, in team order
        return self.deconflict(observations, actions)

    # holds every UAV to the speed it was allocated, and trims its flight so that it neither flies into a
    # UAV it can see nor lands where a team mate has already been sent this step. Cells of the home base
    # are shared airspace and are never blocked: UAVs do not collide there, and blocking them would leave
    # the team circling its own base instead of refilling.
    def deconflict(self, observations, actions):
        reserved = set()
        trimmed = []

        for observation, action in zip(observations, actions):
            _, params = self.allocated(observation.uav_id)
            action = self.cap_speed(action, params)
            action = self.within_sight(action)

            shared = set(observation.base_footprint())
            blocked = (halo(observation.uav_positions, params.separation) | reserved) - shared
            action = avoid(observation.pos, action, blocked)

            reserved.update(flight_path(observation.pos, action))
            trimmed.append(action)

        return trimmed

    # holds an action to the speed this UAV was allocated
    def cap_speed(self, action, params):
        if not action.is_movement():
            return action
        speed = min(action.speed, params.effective_speed())
        return Action(action.direction, speed) if speed > 0 else Action.stay()

    # keeps a UAV from being sent further than it can see. UAV_SPEED may be larger than
    # UAV_OBSERVATION_RADIUS, and a flight that ends outside the observation window lands on a cell that
    # the observation said nothing about, so the UAV can fly into a team mate it was never told was there.
    # The same reasoning as in FirefighterPolicy.within_sight(), applied here to the whole team, whatever
    # policy each of them is flying.
    #
    # Note what this stopped guaranteeing once smoke could occlude. The cap rests on the window being a
    # region the observation described, and a cell inside it that the smoke hid is one the observation said
    # nothing about either -- so deconflict() above can route a UAV into a team mate standing in a plume, at
    # any speed. Staying inside the window is still necessary and is no longer sufficient. There is nothing
    # to do about it here: a policy cannot see through smoke, and pretending the trim is safe would be worse
    # than knowing it is not.
    def within_sight(self, action):
        if not action.is_movement():
            return action
        speed = min(action.speed, config.UAV_OBSERVATION_RADIUS)
        return Action(action.direction, speed) if speed > 0 else Action.stay()

    def __str__(self):
        if not self.table:
            return f"super({self.default} for all)"
        counts = {}
        for policy_name, _ in self.table.values():
            counts[policy_name] = counts.get(policy_name, 0) + 1
        return "super(" + ", ".join(f"{count}x{name}" for name, count in sorted(counts.items())) + ")"
