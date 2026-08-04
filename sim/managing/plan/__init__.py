"""Planners: the step that decides what the team should be flying.

A planner is consulted by a managing system running in this process. A managing system that lives on a
server does its own planning there and never builds one of these; see sim/managing/remote.py.
"""

# own python modules

from .base import Planner
from .local import HeuristicPlanner

__all__ = ["Planner", "HeuristicPlanner"]
