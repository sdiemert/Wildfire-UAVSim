"""Planners: the step that decides what the team should be flying.

To add your own:

  1. create sim/managing/plan/my_planner.py with a Planner subclass that has a unique 'name' and implements
     plan(snapshot, symptoms, knowledge)
  2. import it below and add the class to PLANNERS

It can then be named by a managing system in sim/managing/systems.py, selected for one run with
`--mape planner=my-planner`, and is covered by the parametrised tests in
tests/managing/test_component_contract.py without any further change.

A planner is consulted by a managing system running in this process. A managing system that lives on a
server does its own planning there and never builds one of these; see sim/managing/remote.py.
"""

# own python modules

from ..registry import Registry
from .base import Planner
from .defensive import DefensivePlanner
from .heuristic import HeuristicPlanner
from .static import StaticPlanner

# every planner a managing system may be composed from
PLANNERS = Registry("planner", (HeuristicPlanner, DefensivePlanner, StaticPlanner))

__all__ = ["PLANNERS", "DefensivePlanner", "HeuristicPlanner", "Planner", "StaticPlanner"]
