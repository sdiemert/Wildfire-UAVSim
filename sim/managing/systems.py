"""The managing systems this project knows about, and the factory that builds one.

A managing system is a MAPE-K loop, and what distinguishes one from another is which implementation is
doing each of the five parts and how it is tuned. That is data, not code, so a managing system here is one
frozen record naming five components -- and adding one is one entry in REGISTERED.

To add your own:

  1. write whatever components it needs, and register them in their own package: a planner in
     sim/managing/plan/, an analyser in sim/managing/analyze/, and so on. Reusing the existing ones is
     fine, and several of the systems below do nothing else.
  2. add a ManagingSystemSpec to REGISTERED, naming them

It is then selectable everywhere without another change: `MANAGING_SYSTEM` in config.py,
`headless.py --managing <name>`, the dropdown on the web interface, and the parametrised tests in
tests/managing/test_systems.py, which run every registered system as they find it.

For an experiment that wants a combination worth trying but not worth naming, the components of a
registered system can be overridden one at a time without touching this file:

    python3 headless.py --managing heuristic --mape planner=defensive --mape analyzer=cautious

# Where a managing system lives

'location' is the whole of the difference between running here and running on a server. A local system is
the loop in this process; a remote one reads the sensor here, sends the reading to the server named by its
URL and applies what comes back, with the analysis, the planning and the Knowledge base all over there.
Neither the model, the runner nor the web interface can tell the two apart: both present the same tick(),
name, location and knowledge. See remote.py.
"""

# python libraries

from dataclasses import dataclass, replace

# own python modules

# see the note in sim/policy/random_policy.py about importing config as a module
import config

from .analyze import ANALYZERS
from .execute import EXECUTORS
from .knowledge import KNOWLEDGE_BASES
from .loop import ManagingSystem
from .monitor import MONITORS
from .plan import PLANNERS
from .remote import RemoteManagingSystem

# the five parts of a MAPE-K loop, in the order they run, and where the implementations of each are
# registered. Everything that iterates over the roles -- composing a system, overriding one component of
# it, reporting what ran -- reads this, so a sixth role would be added here and nowhere else.
REGISTRIES = {
    "monitor": MONITORS,
    "analyzer": ANALYZERS,
    "planner": PLANNERS,
    "executor": EXECUTORS,
    "knowledge": KNOWLEDGE_BASES,
}
ROLES = tuple(REGISTRIES)


@dataclass(frozen=True)
class ManagingSystemSpec:
    """One managing system: which component does each job, and how it is tuned.

    A spec is a description and not a loop. Nothing is built until build_managing_system() is given a
    sensor and an effector to build it over, which is what lets the whole catalogue be listed, compared and
    validated without a simulation existing.
    """

    # what it is selected by, and what the interface and the results file call it
    name: str
    description: str = ""

    # 'none' builds nothing at all -- the unmanaged simulation; 'local' runs the loop in this process;
    # 'remote' runs everything but the sensor and the effector on a server
    location: str = "local"

    # the five components, each a name registered for its role. Anything left alone gets the default
    # registered for that role.
    monitor: str = "default"
    analyzer: str = "heuristic"
    planner: str = "heuristic"
    executor: str = "default"
    knowledge: str = "default"

    # tuning. None defers to config.py, so a system only states what it means to do differently.
    period: int | None = None            # None -> ADAPTATION_PERIOD
    hysteresis: int | None = None        # None -> ADAPTATION_HYSTERESIS

    # remote only. None defers to MANAGING_SYSTEM_URL; 'fallback' names the local system that stands in
    # for an evaluation the server could not answer, and None means the team simply keeps flying what it
    # had. Both are ignored by a local system.
    url: str | None = None
    fallback: str | None = None

    # the five components as a mapping, which is what the loop, the runner and the interface report
    def components(self):
        return {role: getattr(self, role) for role in ROLES}

    # the same system with some of its components replaced, for an experiment that wants a combination
    # nobody has named. Every role and every component name is checked here, so a mistyped one fails
    # before a batch of runs starts rather than inside a worker.
    def with_components(self, components):
        if not components:
            return self

        chosen = {}
        for role, name in components.items():
            if role not in REGISTRIES:
                raise KeyError(f"unknown MAPE-K role {role!r}, available: {', '.join(ROLES)}")
            REGISTRIES[role].lookup(name)  # raises, listing what is registered for that role
            chosen[role] = name

        return replace(self, **chosen)

    # one line for --list-managing and the logs. A remote system's components are not listed, because they
    # are the server's and this side is not told what they are.
    def describe(self):
        if self.location == "none":
            return f"{self.name}: nothing runs"
        if self.location == "remote":
            return f"{self.name} (remote): {self.url or config.MANAGING_SYSTEM_URL}" + (
                f", falling back to {self.fallback}" if self.fallback else "")
        parts = " ".join(f"{role[0].upper()}={name}" for role, name in self.components().items())
        return f"{self.name} (local): {parts}"


# every managing system that can be selected by name. The first three are the arms of the experiment the
# managing system exists to settle: no managing system, a managing system that does not adapt, and one
# that does.
REGISTERED = (
    ManagingSystemSpec(
        name="none",
        location="none",
        description="no managing system: every UAV flies the policy the run was started with, for the "
                    "whole run. The unmanaged baseline.",
    ),
    ManagingSystemSpec(
        name="static",
        planner="static",
        description="the loop runs but never reallocates: the team flies under SuperPolicy, which "
                    "dispatches per UAV and keeps the fleet apart, without anything being adapted. The "
                    "control that separates what SuperPolicy is worth from what adapting is worth.",
    ),
    ManagingSystemSpec(
        name="heuristic",
        description="the default: threat to the base and crowding read off each snapshot, and policies "
                    "allocated by the rules in plan/heuristic.py, damped by hysteresis.",
    ),
    ManagingSystemSpec(
        name="defensive",
        analyzer="cautious",
        planner="defensive",
        description="the base over everything else: threat reported further out, a larger detachment sent "
                    "to defend it, and crowding left to SuperPolicy rather than answered with dispersal.",
    ),
    ManagingSystemSpec(
        name="reactive",
        period=1,
        hysteresis=1,
        description="the default components with the damping removed: every evaluation is acted on at "
                    "once. Reacts a step or two sooner and thrashes when a symptom sits on a threshold.",
    ),
    ManagingSystemSpec(
        name="remote",
        location="remote",
        fallback="heuristic",
        description="the whole loop on the server at MANAGING_SYSTEM_URL: the sensor is read here and the "
                    "reading sent over, and the analysis, the planning and the Knowledge base are all "
                    "over there.",
    ),
)

# name -> spec, used by the --managing option, the web interface dropdown and config.MANAGING_SYSTEM
MANAGING_SYSTEMS = {spec.name: spec for spec in REGISTERED}

# older names kept working. 'local' was what the default managing system was called when there was only
# one of them and the setting said where it ran rather than which it was.
ALIASES = {"local": "heuristic"}


# the spec registered under a name, raising a helpful error for unknown ones the way build_policy() does
def managing_system(name):
    resolved = ALIASES.get(str(name), str(name))
    if resolved not in MANAGING_SYSTEMS:
        raise KeyError(f"unknown managing system {name!r}, "
                       f"available: {', '.join(sorted(MANAGING_SYSTEMS))}")
    return MANAGING_SYSTEMS[resolved]


# builds the managing system named by 'managing', or by MANAGING_SYSTEM when that is None, over the sensor
# and effector it is given. 'components' overrides individual parts of it, as --mape does. 'url' overrides
# where a remote one lives.
#
# 'none' has no managing system and returns None, which is what tells AdaptiveWildFireModel to be the plain
# simulation.
def build_managing_system(sensor, effector, managing=None, components=None, url=None, log=None):
    spec = managing_system(config.MANAGING_SYSTEM if managing is None else managing)
    spec = spec.with_components(components)

    if spec.location == "none":
        return None

    # the spec is what knows which settings are actually in play, so the bounds are checked here rather
    # than in whichever caller happened to build it: a run started from the web interface then gets the
    # same checks a headless one does, and the remote settings are only checked by a system that uses them
    config.validate(managing=spec.name, remote=spec.location == "remote")

    if spec.location == "local":
        return build_local(spec, sensor, effector, log)

    if spec.location == "remote":
        # a factory rather than an instance, so that a run which never loses its server never builds the
        # local system it does not use
        fallback = None
        if config.MANAGING_SYSTEM_FALLBACK and spec.fallback:
            stand_in = managing_system(spec.fallback)

            def fallback():  # noqa: F811 - the name is the factory either way
                return build_local(stand_in, sensor, effector, log)

        return RemoteManagingSystem(sensor=sensor, effector=effector, name=spec.name,
                                    url=url if url is not None else spec.url,
                                    period=spec.period, fallback=fallback, log=log)

    raise ValueError(f"managing system {spec.name!r} has an unknown location {spec.location!r}, "
                     f"expected one of 'none', 'local', 'remote'")


# assembles a local loop from a spec. Separate because a remote managing system builds one of these to
# stand in for a server it cannot reach.
def build_local(spec, sensor, effector, log=None):
    return ManagingSystem(sensor=sensor, effector=effector, name=spec.name, log=log,
                          period=spec.period, hysteresis=spec.hysteresis, **spec.components())
