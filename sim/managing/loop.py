"""The MAPE-K loop itself, and the factory that assembles one.

ManagingSystem owns the four steps and the Knowledge base they share, and does nothing else. It holds no
reference to the simulation: the only things it was given that touch it are a sensor and an effector, both
of which it knows only through the interfaces in ports.py.

Who calls tick(), and when, is not decided here either. AdaptiveWildFireModel calls it once before each
simulation step (see sim/adaptive.py), which is what makes an allocation take effect on the step after the
reading it was planned from -- a managing system that observes and then acts, rather than one that reaches
into the middle of a step.

The same loop can run somewhere else entirely: see remote.py, which presents this class's surface and
forwards every decision to a server.
"""

# own python modules

# see the note in sim/policy/random_policy.py about importing config as a module
import config

from .analyze import HeuristicAnalyzer
from .execute import Executor
from .knowledge import Knowledge
from .monitor import Monitor
from .plan.local import HeuristicPlanner
from .remote import RemoteManagingSystem


class ManagingSystem:
    """Monitor, Analyse, Plan and Execute over a shared Knowledge base, all in this process.

    One tick is one turn of the loop. Two things can stop a tick early, and both are worth having:

      * the period. With ADAPTATION_PERIOD above 1 most steps are not evaluation points at all, which is
        how the cost of managing is traded against how quickly it reacts.

      * a clean bill of health. If the analyser finds nothing wrong, the loop returns before Plan runs.
    """

    name = "local"

    # constructor
    def __init__(self, sensor, effector, analyzer=None, planner=None, knowledge=None,
                 period=None, log=None):
        self.knowledge = Knowledge() if knowledge is None else knowledge
        self.analyzer = HeuristicAnalyzer() if analyzer is None else analyzer
        self.planner = HeuristicPlanner() if planner is None else planner
        self.monitor = Monitor(sensor, self.knowledge, log=log)
        self.executor = Executor(effector, self.knowledge, log=log)
        self.period = config.ADAPTATION_PERIOD if period is None else max(1, int(period))
        self.log = log
        # how many times the loop has run to completion, as opposed to being skipped by the period or
        # short circuited by a clean bill of health
        self.evaluations = 0

    # whether this step is one the loop runs on
    def due(self, step):
        return step % self.period == 0

    # one turn of the loop. Returns the Allocation that was applied, or None on a step where the loop did
    # not run or found nothing worth changing.
    def tick(self, step):
        if not self.due(step):
            return None

        self.evaluations += 1

        snapshot = self.monitor.observe()        # M
        allocation = self.plan_for(snapshot)     # A, then P

        if allocation is None or not allocation.directives:
            return None

        self.executor.execute(allocation)        # E
        return allocation

    # Analyse and Plan for a snapshot somebody else took. This is what a remote managing system falls back
    # to when its server cannot be reached: the snapshot has already been read, so only the deciding is
    # wanted. It is recorded first, because the analysis reads the history to tell a fire closing on the
    # base from one burning itself out at the same distance.
    def decide(self, snapshot):
        self.knowledge.record(snapshot)
        return self.plan_for(snapshot)

    # the deciding half of a turn: what is wrong, and what to do about it. None when nothing is wrong.
    def plan_for(self, snapshot):
        symptoms = self.analyzer.analyze(snapshot, self.knowledge)     # A

        if not symptoms.requires_adaptation():
            if self.log is not None:
                self.log.debug("step %d: nothing to adapt to", snapshot.step)
            return None

        return self.planner.plan(snapshot, symptoms, self.knowledge)   # P

    # how many times the allocation has actually changed over the run, which the status panel reports
    def adaptations(self):
        return self.knowledge.adaptations

    def __str__(self):
        return f"local MAPE-K, every {self.period} step(s)"


# builds the managing system named by 'managing', or by MANAGING_SYSTEM when that is None, over the sensor
# and effector it is given. 'none' has no managing system and returns None, which is what tells
# AdaptiveWildFireModel to be the plain simulation.
#
# A remote one is given a factory for a local one to stand in with, unless MANAGING_SYSTEM_FALLBACK says
# otherwise. It is a factory rather than an instance so that a run which never loses its server never
# builds a managing system it does not use.
def build_managing_system(sensor, effector, managing=None, url=None, log=None):
    name = config.MANAGING_SYSTEM if managing is None else str(managing)

    if name == "none":
        return None

    if name == "local":
        return ManagingSystem(sensor=sensor, effector=effector, log=log)

    if name == "remote":
        fallback = None
        if config.MANAGING_SYSTEM_FALLBACK:
            def fallback():  # noqa: F811 - the name is the factory either way
                return ManagingSystem(sensor=sensor, effector=effector, log=log)

        return RemoteManagingSystem(sensor=sensor, effector=effector, url=url,
                                    fallback=fallback, log=log)

    raise KeyError(f"unknown managing system {name!r}, available: {', '.join(config.MANAGING_SYSTEMS)}")
