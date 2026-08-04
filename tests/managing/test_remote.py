"""Tests for a managing system that lives on a server.

The failure paths matter more than the happy one. What this architecture claims is that losing the managing
system costs a run its adaptation quality and not the run, and that is only true if every way a server can
let us down ends in a fallback rather than an exception.

RemoteManagingSystem takes a 'transport', so all of this runs without a server, a socket or a port.
"""

# python libraries

import json
import urllib.error

import pytest

# own python modules

from sim.managing.contract import Allocation, UavDirective
from sim.managing.loop import ManagingSystem
from sim.managing.ports import Effector, Sensor
from sim.managing.remote import RemoteManagingSystem


class FakeSensor(Sensor):
    def __init__(self, state):
        self.state = state
        self.reads = 0

    def read(self):
        self.reads += 1
        return self.state


class FakeEffector(Effector):
    def __init__(self):
        self.applied = []

    def apply(self, allocation):
        self.applied.append(allocation)
        return len(allocation.directives)


@pytest.fixture
def state(snapshot):
    # something is wrong with UAV 0, so the local fallback has a reason to plan
    return snapshot(uavs=[{"uav_id": 0, "pos": (5, 5), "hp": 1}, {"uav_id": 1, "pos": (9, 9)}], step=7)


@pytest.fixture
def parts(state):
    return FakeSensor(state), FakeEffector()


def transport_returning(body, record=None):
    def _transport(url, payload, timeout):
        if record is not None:
            record.append((url, payload, timeout))
        return body if isinstance(body, bytes) else json.dumps(body).encode()
    return _transport


def transport_raising(exc):
    def _transport(url, payload, timeout):
        raise exc
    return _transport


def build(parts, **kwargs):
    sensor, effector = parts
    kwargs.setdefault("url", "http://server/manage")
    return RemoteManagingSystem(sensor=sensor, effector=effector, **kwargs)


def local_fallback(parts):
    sensor, effector = parts
    return lambda: ManagingSystem(sensor=sensor, effector=effector)


# --- the happy path ---------------------------------------------------------


def test_the_allocation_the_server_sends_is_applied(parts):
    sensor, effector = parts
    system = build(parts, transport=transport_returning({
        "step": 7, "rationale": "server says so",
        "directives": [{"uav_id": 0, "policy": "disperse", "params": {"separation": 3}}],
    }))

    allocation = system.tick(0)

    assert [(d.uav_id, d.policy) for d in allocation.directives] == [(0, "disperse")]
    assert allocation.rationale == "server says so"
    assert effector.applied == [allocation]
    assert system.failures == 0


def test_the_server_is_sent_the_raw_snapshot(parts):
    sent = []
    system = build(parts, timeout=1.5, transport=transport_returning({"directives": []}, record=sent))
    system.tick(0)

    url, payload, timeout = sent[0]
    assert (url, timeout) == ("http://server/manage", 1.5)
    assert json.dumps(payload)                       # it has to be serialisable
    assert payload["snapshot"]["step"] == 7
    assert payload["snapshot"]["uavs"][0]["uav_id"] == 0
    assert payload["step"] == 7


# the analysis is the server's job, so nothing resembling a local diagnosis may be in the request. This is
# the difference between a remote managing system and a remote planner, and it is worth pinning down.
def test_no_local_analysis_is_sent(parts):
    sent = []
    system = build(parts, transport=transport_returning({"directives": []}, record=sent))
    system.tick(0)
    assert "symptoms" not in sent[0][1]


# ... and for the same reason a quiet step still reaches the server: deciding that nothing needs doing is
# the server's decision to make, not this side's
def test_a_quiet_step_still_reaches_the_server(parts, snapshot):
    sensor, _ = parts
    sensor.state = snapshot(uavs=[{"uav_id": 0, "pos": (2, 2)}], step=3)   # nothing wrong at all
    sent = []
    system = build(parts, transport=transport_returning({"directives": []}, record=sent))

    system.tick(0)
    assert len(sent) == 1, "the local side must not decide the server is not worth consulting"


def test_each_run_identifies_itself(parts):
    # headless.py --workers N has N runs in flight against one server, and a server keeping a Knowledge
    # base between requests has to key it by run
    sent = []
    system = build(parts, session="abc123", transport=transport_returning({"directives": []}, record=sent))
    system.tick(0)
    assert sent[0][1]["session"] == "abc123"


def test_sessions_differ_between_runs(parts):
    assert build(parts).session != build(parts).session


def test_the_step_is_stamped_locally_not_taken_from_the_server(parts):
    system = build(parts, transport=transport_returning(
        {"step": 999, "directives": [{"uav_id": 0, "policy": "disperse"}]}))
    assert system.tick(0).step == 7


# --- the period -------------------------------------------------------------


def test_the_period_skips_steps(parts):
    sensor, _ = parts
    system = build(parts, period=3, transport=transport_returning({"directives": []}))
    for step in range(9):
        system.tick(step)
    assert sensor.reads == 3
    assert system.requests == 3


# --- every way a server can let us down -------------------------------------


@pytest.mark.parametrize("failure, description", [
    (transport_raising(urllib.error.URLError("connection refused")), "the server is not listening"),
    (transport_raising(TimeoutError("timed out")), "the server is too slow"),
    (transport_raising(urllib.error.HTTPError("http://server", 500, "boom", {}, None)), "a 500"),
    (transport_returning(b"not json at all"), "a body that is not JSON"),
    (transport_returning({"directives": [{"policy": "disperse"}]}), "a directive with no uav_id"),
    (transport_returning({"directives": "not a list"}), "JSON that is not an allocation"),
])
def test_every_failure_falls_back_instead_of_raising(parts, failure, description):
    system = build(parts, fallback=local_fallback(parts), transport=failure)

    allocation = system.tick(0)          # must not raise, whatever happened

    assert system.failures == 1, description
    assert allocation is not None and allocation.directives, \
        f"the local stand-in should still have planned something after {description}"
    assert "unreachable" in allocation.rationale


def test_the_stand_in_produces_what_a_local_managing_system_would(parts):
    sensor, effector = parts
    remote = build(parts, fallback=local_fallback(parts),
                   transport=transport_raising(urllib.error.URLError("refused")))
    local = ManagingSystem(sensor=FakeSensor(sensor.state), effector=FakeEffector())

    assert remote.tick(0).directives == local.tick(0).directives


def test_the_stand_in_is_built_once_and_kept(parts):
    system = build(parts, fallback=local_fallback(parts),
                   transport=transport_raising(urllib.error.URLError("refused")))
    system.tick(0)
    first = system.fallback
    system.tick(1)
    assert system.fallback is first, "a server that stays down must not cost a rebuild per step"


def test_the_stand_in_is_not_built_at_all_while_the_server_answers(parts):
    system = build(parts, fallback=local_fallback(parts),
                   transport=transport_returning({"directives": []}))
    system.tick(0)
    assert system.fallback is None


def test_without_a_stand_in_the_team_is_left_on_what_it_is_flying(parts):
    sensor, effector = parts
    system = build(parts, fallback=None, transport=transport_raising(urllib.error.URLError("refused")))

    assert system.tick(0) is None
    assert effector.applied == []


def test_failures_are_counted_so_a_result_can_be_read_honestly(parts):
    system = build(parts, fallback=local_fallback(parts),
                   transport=transport_raising(urllib.error.URLError("refused")))
    for step in range(3):
        system.tick(step)
    assert (system.requests, system.failures) == (3, 3)


# --- the contract -----------------------------------------------------------


def test_a_server_may_speak_about_only_one_uav(parts):
    system = build(parts, transport=transport_returning({
        "directives": [{"uav_id": 1, "policy": "defend-base"}]}))
    assert [d.uav_id for d in system.tick(0).directives] == [1]


def test_no_directives_means_nothing_to_change(parts):
    sensor, effector = parts
    system = build(parts, transport=transport_returning({"directives": [], "rationale": "all fine"}))
    assert system.tick(0) is None
    assert effector.applied == []


def test_params_may_be_omitted(parts):
    system = build(parts, transport=transport_returning({
        "directives": [{"uav_id": 0, "policy": "random"}]}))
    assert system.tick(0).directives[0].params == {}


# an unknown policy name is not this module's problem: parsing succeeds, and the effector refuses it. This
# records the division of responsibility that keeps a bad server from crashing a run at any layer.
def test_an_unknown_policy_name_is_parsed_here_and_refused_later(parts):
    system = build(parts, transport=transport_returning({
        "directives": [{"uav_id": 0, "policy": "no-such-policy"}]}))
    allocation = system.tick(0)
    assert allocation.directives[0].policy == "no-such-policy"
    assert system.failures == 0


def test_the_response_shape_is_what_a_server_author_writes(parts):
    payload = Allocation(step=1, rationale="r", directives=(UavDirective(0, "disperse", {}),)).to_json()
    assert payload == {"step": 1, "rationale": "r",
                       "directives": [{"uav_id": 0, "policy": "disperse", "params": {}}]}


# --- the surface it shares with the local one -------------------------------


def test_it_presents_the_same_surface_as_the_local_managing_system(parts):
    """AdaptiveWildFireModel, the runner and the status panel must not be able to tell the two apart."""
    system = build(parts, transport=transport_returning({"directives": []}))
    for name in ("tick", "due", "adaptations", "knowledge", "evaluations", "period"):
        assert hasattr(system, name), name


def test_adaptations_are_counted(parts):
    system = build(parts, transport=transport_returning({
        "directives": [{"uav_id": 0, "policy": "disperse"}]}))
    system.tick(0)
    assert system.adaptations() == 1
