"""Tests for the MAPE-K loop itself: when it runs, when it does not, and what it records.

The loop is driven through fake ports, which is the point of the ports existing: none of this needs a
model, a grid or mesa, because the managing system has never been able to see one.
"""

# python libraries

import pytest

# own python modules

from sim.managing.contract import Allocation, Symptoms, UavDirective
from sim.managing.knowledge import Knowledge
from sim.managing.loop import ManagingSystem, build_managing_system
from sim.managing.plan.base import Planner
from sim.managing.plan.local import HeuristicPlanner
from sim.managing.remote import RemoteManagingSystem
from sim.managing.ports import Effector, Sensor


class FakeSensor(Sensor):
    """Hands back a snapshot the test prepared, and counts how often it was asked."""

    def __init__(self, state):
        self.state = state
        self.reads = 0

    def read(self):
        self.reads += 1
        return self.state


class FakeEffector(Effector):
    """Records what it was asked to apply, and applies all of it."""

    def __init__(self):
        self.applied = []

    def apply(self, allocation):
        self.applied.append(allocation)
        return len(allocation.directives)


class FixedPlanner(Planner):
    """Always asks for the same thing, and counts how often it was consulted."""

    name = "fixed"

    def __init__(self, policy="disperse"):
        self.policy = policy
        self.calls = 0

    def plan(self, snapshot, symptoms, knowledge):
        self.calls += 1
        return Allocation(step=snapshot.step, rationale="fixed",
                          directives=tuple(UavDirective(report.uav_id, self.policy)
                                           for report in snapshot.alive()))


class SilentAnalyzer:
    """Finds nothing wrong, whatever it is shown."""

    def analyze(self, snapshot, knowledge):
        return Symptoms(flying=len(snapshot.alive()))


class NoisyAnalyzer:
    """Always finds something wrong."""

    def analyze(self, snapshot, knowledge):
        return Symptoms(base_threat=2, flying=len(snapshot.alive()))


@pytest.fixture
def parts(snapshot):
    state = snapshot(uavs=[{"uav_id": 0, "pos": (5, 5)}, {"uav_id": 1, "pos": (9, 9)}])
    return FakeSensor(state), FakeEffector()


def build(parts, **kwargs):
    sensor, effector = parts
    kwargs.setdefault("analyzer", NoisyAnalyzer())
    kwargs.setdefault("planner", FixedPlanner())
    return ManagingSystem(sensor=sensor, effector=effector, **kwargs)


# --- the loop runs ----------------------------------------------------------


def test_a_tick_runs_all_four_steps(parts):
    sensor, effector = parts
    system = build(parts, period=1)

    allocation = system.tick(0)

    assert sensor.reads == 1                        # Monitor
    assert system.planner.calls == 1                # Plan
    assert effector.applied == [allocation]         # Execute
    assert system.knowledge.latest() is sensor.state  # Knowledge


def test_the_allocation_reaches_the_effector(parts):
    sensor, effector = parts
    build(parts, period=1).tick(0)
    assert [(d.uav_id, d.policy) for d in effector.applied[0].directives] == \
           [(0, "disperse"), (1, "disperse")]


# --- when it does not run ---------------------------------------------------


def test_the_period_skips_steps(parts):
    sensor, effector = parts
    system = build(parts, period=3)

    for step in range(9):
        system.tick(step)

    assert sensor.reads == 3, "the loop should have run on steps 0, 3 and 6 only"
    assert system.evaluations == 3


def test_a_skipped_step_reads_nothing_at_all(parts):
    sensor, _ = parts
    system = build(parts, period=5)
    system.tick(1)
    assert sensor.reads == 0, "a step that is not an evaluation point must not even take a reading"


# the short circuit is what keeps a managing system that runs every step affordable, and with the remote
# planner it is the difference between a request per step and a request per event
def test_a_clean_bill_of_health_stops_before_planning(parts):
    sensor, effector = parts
    system = build(parts, period=1, analyzer=SilentAnalyzer())

    assert system.tick(0) is None
    assert sensor.reads == 1, "it still monitors"
    assert system.planner.calls == 0, "but it does not plan"
    assert effector.applied == []


def test_a_plan_with_nothing_in_it_is_not_executed(parts, snapshot):
    class SaysNothing(Planner):
        name = "quiet"

        def plan(self, snapshot, symptoms, knowledge):
            return Allocation(step=snapshot.step)

    sensor, effector = parts
    system = build(parts, period=1, planner=SaysNothing())
    assert system.tick(0) is None
    assert effector.applied == []


# --- what it remembers ------------------------------------------------------


def test_repeating_the_same_allocation_is_not_a_new_adaptation(parts):
    system = build(parts, period=1)
    for step in range(4):
        system.tick(step)
    assert system.adaptations() == 1, "the allocation was only ever decided once"


def test_changing_the_allocation_counts_as_an_adaptation(parts):
    system = build(parts, period=1)
    system.tick(0)
    system.planner.policy = "defend-base"
    system.tick(1)
    assert system.adaptations() == 2


def test_a_destroyed_uav_is_forgotten(parts, snapshot):
    sensor, _ = parts
    system = build(parts, period=1)
    system.knowledge.want(0, "disperse")

    sensor.state = snapshot(uavs=[{"uav_id": 0, "pos": None, "alive": False}])
    system.tick(0)
    assert 0 not in system.knowledge.streaks


def test_the_history_is_bounded(snapshot):
    knowledge = Knowledge(history=3)
    for step in range(10):
        knowledge.record(snapshot(step=step))
    assert len(knowledge.history) == 3
    assert knowledge.latest().step == 9


# --- the factory ------------------------------------------------------------


def test_the_factory_builds_a_local_managing_system(parts):
    sensor, effector = parts
    system = build_managing_system(sensor, effector, managing="local")
    assert isinstance(system, ManagingSystem)
    assert isinstance(system.planner, HeuristicPlanner)


def test_the_factory_builds_a_remote_managing_system(parts):
    sensor, effector = parts
    system = build_managing_system(sensor, effector, managing="remote", url="http://server/manage")
    assert isinstance(system, RemoteManagingSystem)
    assert system.url == "http://server/manage"


def test_a_remote_managing_system_is_given_a_local_stand_in(parts, sim_config):
    sim_config(MANAGING_SYSTEM_FALLBACK=True)
    sensor, effector = parts
    system = build_managing_system(sensor, effector, managing="remote")
    # a factory rather than an instance, so a run that never loses its server never builds one
    assert callable(system.fallback_factory)
    assert isinstance(system.fallback_factory(), ManagingSystem)


def test_the_stand_in_can_be_refused(parts, sim_config):
    """The honest setting for an experiment about what happens when a managing system goes away."""
    sim_config(MANAGING_SYSTEM_FALLBACK=False)
    sensor, effector = parts
    assert build_managing_system(sensor, effector, managing="remote").fallback_factory is None


def test_the_factory_builds_nothing_for_none(parts):
    sensor, effector = parts
    assert build_managing_system(sensor, effector, managing="none") is None


def test_the_factory_rejects_a_managing_system_it_does_not_have(parts):
    sensor, effector = parts
    with pytest.raises(KeyError, match="local"):
        build_managing_system(sensor, effector, managing="telepathy")
