"""The managing system: a MAPE-K loop that decides what each UAV should be flying.

The simulation on its own is a *managed system*. Every UAV flies one policy, chosen before the run starts,
and nothing reconsiders it however the run goes. This package is the *managing system* placed over the top
of it, which watches how the run is going and reallocates policies to keep the home base standing and to
keep the team from flying into itself.

# Independence

Nothing in this package imports the simulation. Not the model, not the agents, not the policies, not mesa.
The only things it is given are a Sensor and an Effector (ports.py), and the only things that pass through
them are the frozen messages in contract.py. tests/managing/test_independence.py walks every module here
and fails if that ever stops being true.

That is a stronger property than tidiness. It means the managing system cannot come to depend on anything
it was not told, so what it achieves is achieved with the information the sensor actually reports -- and it
means the whole Plan step can be moved to another process or another machine without redesigning anything,
because it was never able to reach the simulation in the first place. See plan/remote.py.

# The loop

    ManagingSystem.tick(step)
        Monitor   sensor.read()          -> FleetSnapshot   -> Knowledge
        Analyze   snapshot + Knowledge   -> Symptoms        (returns early if nothing is wrong)
        Plan      snapshot + Symptoms    -> Allocation
        Execute   effector.apply()       -> Knowledge

# Which managing system

Each of the five steps is a role with several implementations to choose from, registered in the package it
lives in, and a *managing system* is one named combination of them: which analyser, which planner, how
often it evaluates and how hard it damps. They are listed in systems.py, `MANAGING_SYSTEM` names the one to
run, and adding another is one entry in a tuple. That is what makes an experiment about how to manage this
fleet a matter of running the same seeds against a different name.

    'none'       no managing system; every UAV flies one policy for the whole run
    'static'     the loop runs but never reallocates: the control arm
    'heuristic'  the default: rules over threat to the base and crowding, damped by hysteresis
    'defensive'  the base over everything else
    'reactive'   the default components with the damping removed
    'remote'     the whole loop on a server

# Where it runs

A managing system is in this process or on a server, as a whole -- its `location`. A local one is
ManagingSystem (loop.py), with the four steps and the Knowledge base all here. A remote one is
RemoteManagingSystem (remote.py): the sensor is read here and the reading sent to a server, which analyses
it, plans against its own Knowledge base and answers with an allocation.

The sensor and the effector stay local in both cases, because they are the simulation's own interface and
can be nowhere else -- in a real deployment they would be the radio link to the fleet. Everything that
could be called deciding is on whichever side the location names.

The adapters that satisfy the two ports live in sim/adapters.py, which is the one module in the project
that imports both the managing and the managed system.
"""

# own python modules

from .analyze import ANALYZERS, Analyzer, CautiousAnalyzer, HeuristicAnalyzer
from .contract import Allocation, BaseReport, FleetSnapshot, Symptoms, UavDirective, UavReport
from .execute import EXECUTORS, Executor
from .knowledge import KNOWLEDGE_BASES, Knowledge
from .loop import ManagingSystem
from .monitor import MONITORS, Monitor
from .plan import PLANNERS, DefensivePlanner, HeuristicPlanner, Planner, StaticPlanner
from .ports import Effector, Sensor
from .registry import Registry
from .remote import RemoteManagingSystem
from .systems import (ALIASES, MANAGING_SYSTEMS, REGISTERED, REGISTRIES, ROLES, ManagingSystemSpec,
                      build_local, build_managing_system, managing_system)

__all__ = ["ALIASES", "ANALYZERS", "Allocation", "Analyzer", "BaseReport", "CautiousAnalyzer",
           "DefensivePlanner", "EXECUTORS", "Effector", "Executor", "FleetSnapshot", "HeuristicAnalyzer",
           "HeuristicPlanner", "KNOWLEDGE_BASES", "Knowledge", "MANAGING_SYSTEMS", "MONITORS",
           "ManagingSystem", "ManagingSystemSpec", "Monitor", "PLANNERS", "Planner", "REGISTERED",
           "REGISTRIES", "ROLES", "Registry", "RemoteManagingSystem", "Sensor", "StaticPlanner",
           "Symptoms", "UavDirective", "UavReport", "build_local", "build_managing_system",
           "managing_system"]
