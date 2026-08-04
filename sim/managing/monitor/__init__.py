"""Monitors: the step that takes a reading of the managed system and remembers it.

To add your own:

  1. create sim/managing/monitor/my_monitor.py with a Monitor subclass that has a unique 'name' and
     implements observe()
  2. import it below and add the class to MONITORS

It can then be named by a managing system in sim/managing/systems.py, selected for one run with
`--mape monitor=my-monitor`, and is covered by the parametrised tests in tests/managing/test_systems.py
without any further change.

There is one of them, and that is not an oversight. Everything that could be called monitoring logic --
what is worth reporting, and how much of the world a managing system is allowed to see -- belongs to the
sensor, on the managed side, because it is a property of the system being managed. What is left for a
monitor to vary is when a reading is taken and what happens to it on the way in: sampling it, ageing it,
holding several and reporting a smoothed one, or dropping readings to simulate a lossy link.

A managing system that lives on a server still monitors here, because the sensor can only be where the
simulation is; see sim/managing/remote.py.
"""

# own python modules

from ..registry import Registry
from .base import Monitor

# every monitor a managing system may be composed from
MONITORS = Registry("monitor", (Monitor,))

__all__ = ["MONITORS", "Monitor"]
