"""Executors: the step that puts an allocation into effect and records what actually took.

To add your own:

  1. create sim/managing/execute/my_executor.py with an Executor subclass that has a unique 'name' and
     implements execute(allocation)
  2. import it below and add the class to EXECUTORS

It can then be named by a managing system in sim/managing/systems.py, selected for one run with
`--mape executor=my-executor`, and is covered by the parametrised tests in tests/managing/test_systems.py
without any further change.

There is one of them, and that is not an oversight. The judgement about what may be applied belongs to the
effector, on the managed side, because it is the managed system that knows what a valid order is. What is
left for an executor to vary is what happens to a plan on the way out: applying it in stages, applying only
the part of it that has changed, or writing it to a log without applying anything -- which is how a
managing system would be evaluated against a run it is not allowed to steer.

A managing system that lives on a server still executes here, because the effector can only be where the
simulation is; see sim/managing/remote.py.
"""

# own python modules

from ..registry import Registry
from .base import Executor

# every executor a managing system may be composed from
EXECUTORS = Registry("executor", (Executor,))

__all__ = ["EXECUTORS", "Executor"]
