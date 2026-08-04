"""The E of MAPE-K: put the plan into effect, and record what actually took.

Executor is both the role and the only implementation of it so far, which is why this file is called
base.py and holds a concrete class rather than an abstract one. An executor that stages a plan, applies
part of it, or logs it without applying anything would be a sibling of it here, and would be registered
alongside it in __init__.py; nothing else would change, because the loop only ever asks its executor to
execute() an allocation.
"""


class Executor:
    """Hands an allocation to the effector and files the outcome in the Knowledge base.

    Like Monitor, this is thin on purpose: the judgement about what may be applied belongs to the effector,
    on the managed side, because it is the managed system that knows what a valid order is. What Executor
    adds is the record. It notes what was asked for and how much of it took, so that the next evaluation
    plans against what the managed system is actually doing rather than against what the last plan hoped it
    would be doing -- which is the difference between a closed loop and an open one.
    """

    # the name this executor is registered and selected under
    name = "default"

    # constructor
    def __init__(self, effector, knowledge, log=None):
        self.effector = effector
        self.knowledge = knowledge
        self.log = log

    # applies an allocation. Returns the number of directives that were actually applied, which is fewer
    # than were asked for when the effector rejected some.
    def execute(self, allocation):
        applied = self.effector.apply(allocation)
        changed = self.knowledge.record_allocation(allocation, applied)

        if self.log is not None and changed and allocation.directives:
            self.log.info("adaptation at step %d: %s", allocation.step, allocation)
            if applied < len(allocation.directives):
                self.log.warning("only %d of %d directive(s) were applied",
                                 applied, len(allocation.directives))
        return applied

    def __str__(self):
        return self.name
