"""The K of MAPE-K: what the managing system remembers between evaluations.

Monitor writes snapshots into it, Analyse and Plan read them, and Execute records what was actually
applied. It is the only mutable thing on the managing side; everything else is a frozen message or a
stateless component, which is what makes the loop easy to reason about and easy to test.

Two things in here earn their keep:

  * **history**, bounded, so that a long run does not grow without limit. Only the last few entries are
    ever consulted -- a trend over three or four evaluations is enough to tell a fire that is closing in
    from one that is burning out.

  * **streaks**, which is what hysteresis is built on. A UAV whose symptoms sit right on a threshold would
    otherwise be given a new policy every evaluation and spend the run turning round instead of flying
    anywhere. Counting how many evaluations in a row have wanted the same thing, and only acting once that
    reaches ADAPTATION_HYSTERESIS, costs a step or two of reaction time and buys stability.
"""

# python libraries

from collections import deque

# own python modules

# see the note in sim/policy/random_policy.py about importing config as a module
import config


class Knowledge:
    """What the managing system knows, and how sure it is of it."""

    # constructor. 'history' bounds how many snapshots are kept; it defaults to the configured value, read
    # at construction because the deque has to be sized once.
    def __init__(self, history=None):
        limit = config.MANAGING_KNOWLEDGE_HISTORY if history is None else history
        self.history = deque(maxlen=max(1, int(limit)))
        # the allocation currently in force, and the last one that was actually applied to the managed
        # system. They differ when an effector rejected part of a plan.
        self.current = None
        self.applied = 0
        # uav id -> (policy name, how many evaluations in a row have wanted it)
        self.streaks = {}
        # how many times the loop has changed anything, which is what the status panel reports
        self.adaptations = 0
        self.rationale = ""

    # --- monitoring -------------------------------------------------------

    # records a fresh snapshot
    def record(self, snapshot):
        self.history.append(snapshot)
        return snapshot

    # the most recent snapshot, or None before the first one
    def latest(self):
        return self.history[-1] if self.history else None

    # the snapshot from 'back' evaluations ago, or None when the history does not reach that far
    def previous(self, back=1):
        if len(self.history) <= back:
            return None
        return self.history[-1 - back]

    # whether the fire the base can see is closer than it was, which tells a front that is coming for the
    # base from one that is burning itself out. None when there is not enough history to say.
    def base_threat_rising(self):
        latest, previous = self.latest(), self.previous()
        if latest is None or previous is None or latest.base is None or previous.base is None:
            return None
        return latest.base.nearest_fire_distance() < previous.base.nearest_fire_distance()

    # --- hysteresis -------------------------------------------------------

    # records that this evaluation wants 'policy_name' for a UAV, and returns how many evaluations in a row
    # have now wanted it. Wanting something different starts the count again at one.
    def want(self, uav_id, policy_name):
        wanted, streak = self.streaks.get(uav_id, (None, 0))
        streak = streak + 1 if wanted == policy_name else 1
        self.streaks[uav_id] = (policy_name, streak)
        return streak

    # whether a UAV has wanted the same thing for long enough to be given it. The want is recorded either
    # way, so that an evaluation which asks for what the UAV is already flying clears the streak it had
    # built toward something else: hysteresis is meant to damp a policy that keeps being asked for and
    # keeps being dropped, not to let its streak accumulate across the evaluations in between.
    #
    # A UAV that is already flying the policy in question is let through immediately. There is nothing to
    # damp, because applying it changes nothing, and making it wait would stop a plan from restating an
    # allocation that is already correct.
    def settled(self, uav_id, policy_name, current=None):
        streak = self.want(uav_id, policy_name)
        if current == policy_name:
            return True
        return streak >= max(1, config.ADAPTATION_HYSTERESIS)

    # forgets a UAV, so that one destroyed mid run does not hold a streak for the rest of it
    def forget(self, uav_id):
        self.streaks.pop(uav_id, None)

    # --- execution --------------------------------------------------------

    # records the allocation that was applied, and how much of it took
    def record_allocation(self, allocation, applied):
        changed = self.current is None or allocation.directives != self.current.directives
        self.current = allocation
        self.applied = applied
        self.rationale = allocation.rationale
        if changed:
            self.adaptations += 1
        return changed

    # what one UAV was last told to fly, or None when it has never been told anything
    def last_policy(self, uav_id):
        if self.current is None:
            return None
        directive = self.current.for_uav(uav_id)
        return directive.policy if directive is not None else None
