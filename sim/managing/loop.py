"""The MAPE-K loop itself.

ManagingSystem owns the four steps and the Knowledge base they share, and does nothing else. It holds no
reference to the simulation: the only things it was given that touch it are a sensor and an effector, both
of which it knows only through the interfaces in ports.py.

Which five components it is built from is not decided here either. Every one of them is passed in, by name
or as an object, and the names come from a managing system's entry in systems.py -- which is what makes a
managing system something that can be described in a line and selected by name rather than something that
has to be written.

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

from .analyze import ANALYZERS
from .execute import EXECUTORS
from .knowledge import KNOWLEDGE_BASES
from .monitor import MONITORS
from .plan import PLANNERS


class ManagingSystem:
    """Monitor, Analyse, Plan and Execute over a shared Knowledge base, all in this process.

    One tick is one turn of the loop. Two things can stop a tick early, and both are worth having:

      * the period. With ADAPTATION_PERIOD above 1 most steps are not evaluation points at all, which is
        how the cost of managing is traded against how quickly it reacts.

      * a clean bill of health. If the analyser finds nothing wrong, the loop returns before Plan runs.

    The five components are interchangeable, and which combination of them is running is the experiment.
    Nothing in this class knows what any of them do beyond the one method it calls on each.
    """

    # what this managing system is called, and where it runs. Both are read by the status panel and the
    # runner, and RemoteManagingSystem carries the same two, so neither of them has to know which kind it
    # is looking at.
    name = "heuristic"
    location = "local"

    # constructor. Each of the five components may be given as a name to look up in its registry or as an
    # object to use as it is; anything not given falls back to the default registered for its role. Tests
    # and the composition in systems.py use the two ends of that respectively.
    def __init__(self, sensor, effector, name=None, monitor=None, analyzer=None, planner=None,
                 executor=None, knowledge=None, period=None, hysteresis=None, log=None):
        if name is not None:
            self.name = str(name)

        # the Knowledge base is built first, because Monitor and Executor are both given it to write into
        self.knowledge = KNOWLEDGE_BASES.build(knowledge, hysteresis=hysteresis)
        self.monitor = MONITORS.build(monitor, sensor=sensor, knowledge=self.knowledge, log=log)
        self.executor = EXECUTORS.build(executor, effector=effector, knowledge=self.knowledge, log=log)
        self.analyzer = ANALYZERS.build(analyzer)
        self.planner = PLANNERS.build(planner)

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

    # what this managing system is made of, for the log and the status panel. The components are named
    # rather than the roles spelled out, because the names are what a reader would have to type to build it
    # again: "heuristic (local): M=default A=cautious P=defensive E=default K=default, every 1 step(s)".
    def composition(self):
        return {"monitor": self.monitor.name, "analyzer": self.analyzer.name, "planner": self.planner.name,
                "executor": self.executor.name, "knowledge": self.knowledge.name}

    def __str__(self):
        parts = " ".join(f"{role[0].upper()}={name}" for role, name in self.composition().items())
        return f"{self.name} ({self.location}): {parts}, every {self.period} step(s)"
