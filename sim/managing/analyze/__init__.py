"""Analysers: the step that decides what, if anything, is wrong with the managed system.

To add your own:

  1. create sim/managing/analyze/my_analyzer.py with an Analyzer subclass that has a unique 'name' and
     implements analyze(snapshot, knowledge)
  2. import it below and add the class to ANALYZERS

It can then be named by a managing system in sim/managing/systems.py, selected for one run with
`--mape analyzer=my-analyzer`, and is covered by the parametrised tests in
tests/managing/test_component_contract.py without any further change.

A managing system that lives on a server does its own analysis there and never builds one of these; see
sim/managing/remote.py.
"""

# own python modules

from ..registry import Registry
from .base import Analyzer
from .cautious import CautiousAnalyzer
from .heuristic import HeuristicAnalyzer

# every analyser a managing system may be composed from
ANALYZERS = Registry("analyzer", (HeuristicAnalyzer, CautiousAnalyzer))

__all__ = ["ANALYZERS", "Analyzer", "CautiousAnalyzer", "HeuristicAnalyzer"]
