"""A managing system that lives on a server.

# What is remote

The whole of it. Analyse, Plan and the Knowledge base all run on the other side of the socket: the server
is told what the sensor read and answers with what the team should be flying, and nothing on this side
forms an opinion about either.

What stays here is the sensor and the effector, and they stay here because they *are* the simulation's own
interface -- a sensor is a thing that reads a model object and an effector is a thing that writes to one,
and neither can be anywhere other than where the model is. In a real deployment they would be the radio
link to the fleet. So `RemoteManagingSystem` is a proxy: it reads, transmits, receives and applies.

    ManagingSystem       Monitor  Analyse  Plan  Execute  Knowledge      all local
    RemoteManagingSystem Monitor  ───────── server ─────  Execute        decisions all remote

This is a different arrangement from a remote *planner*, which is what this module used to hold. A remote
planner leaves the local side deciding whether anything is wrong at all -- and therefore deciding whether
the server is worth consulting -- which means the managing system is not really over there. Here, a quiet
step is the server's business: it is sent the snapshot like any other and answers with no directives if it
thinks nothing needs doing. The cost is a request per evaluation rather than a request per event, which is
what `ADAPTATION_PERIOD` is for.

# The contract

The client POSTs `application/json` to `MANAGING_SYSTEM_URL`:

    {
      "session": "3f9c1e02",
      "step": 37,
      "snapshot": { ... FleetSnapshot.to_json() ... }
    }

`snapshot` is the whole of what the sensor read: the step, the grid size, one entry per UAV (position,
health, fuel, water, the policy it is flying right now, and what it can see) and the home base with the
fire around it. There is no analysis in the request: working out what is wrong is the server's job.

`session` identifies one run. A server that keeps a Knowledge base between requests -- which it must, to
do anything a single snapshot cannot tell it, such as whether the fire is closing on the base -- has to
key it by this, because `headless.py --workers N` has N runs in flight against one server at once.

The server answers `200` with:

    {
      "step": 37,
      "rationale": "base threat 2 (fire 1.4 cells off): 2 defend-base, 2 firefighter",
      "directives": [
        {"uav_id": 0, "policy": "defend-base", "params": {}},
        {"uav_id": 2, "policy": "disperse", "params": {"separation": 2, "speed_cap": 1}}
      ]
    }

`policy` must name a policy the simulation has registered; `params` may set `speed_cap`, `separation`,
`fuel_reserve` and `extra`, and may be omitted. A UAV left out keeps flying whatever it already was, so
`"directives": []` means "nothing to change". `rationale` is free text and is shown to whoever is watching
the run.

Nothing in the response is trusted. It is parsed here and then validated again, directive by directive, by
AllocationEffector (see sim/adapters.py), which drops anything naming a UAV that does not exist, a UAV that
has been destroyed, a policy that is not registered, or a parameter outside its bounds.

# When the server is not there

Every failure -- connection refused, timeout, a 500, a body that is not JSON, JSON that is not an
allocation -- is caught and logged, and then answered in one of two ways depending on
`MANAGING_SYSTEM_FALLBACK`:

  * True  -- a local managing system, built lazily and kept for the rest of the run, takes that evaluation.
             Losing the server then costs the run its adaptation quality rather than its adaptation.
  * False -- nothing happens and the team keeps flying what it was. This is the honest setting for an
             experiment about what a self-adaptive system does when its managing system goes away.

Either way the run completes. A self-adaptive system whose managing system is reachable over a network has
to degrade when the network does not.
"""

# python libraries

import json
import urllib.error
import urllib.request
import uuid

# own python modules

# see the note in sim/policy/random_policy.py about importing config as a module
import config

from .contract import Allocation
from .execute import Executor
from .knowledge import Knowledge
from .monitor import Monitor


# posts a JSON body and returns the raw response. Separated out so that a test can hand
# RemoteManagingSystem a transport of its own and exercise every branch below without a server, a socket
# or a port.
def post_json(url, payload, timeout):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class RemoteManagingSystem:
    """Stands in, locally, for a managing system that is somewhere else.

    It presents the same surface as ManagingSystem -- tick(), adaptations(), and a knowledge attribute the
    status panel reads -- so AdaptiveWildFireModel, the runner and the web interface cannot tell the two
    apart and none of them needed changing to support this.

    The local Knowledge base it keeps is a record and not a mind: it holds what was applied, so that the
    interface can report it and so that a fallback has somewhere to start, and nothing here ever consults
    it to decide anything. The deciding is all on the server.
    """

    name = "remote"

    # constructor. 'transport' and 'session' exist to be replaced in tests; 'fallback' is the local
    # managing system to stand in when the server cannot be reached, built lazily by the caller-supplied
    # factory so that a run which never loses the server never builds one.
    def __init__(self, sensor, effector, url=None, timeout=None, period=None, fallback=None,
                 log=None, transport=None, session=None):
        self.sensor = sensor
        self.effector = effector
        self.url = config.MANAGING_SYSTEM_URL if url is None else url
        self.timeout = config.MANAGING_SYSTEM_TIMEOUT if timeout is None else timeout
        self.period = config.ADAPTATION_PERIOD if period is None else max(1, int(period))
        self.log = log
        self.transport = post_json if transport is None else transport
        # one run, one session: a server keeping a Knowledge base between requests keys it by this, so
        # that parallel runs against one server do not read each other's history
        self.session = uuid.uuid4().hex[:8] if session is None else session

        # a record of what was applied, for the interface and the runner. Not consulted to decide anything.
        self.knowledge = Knowledge()
        self.evaluations = 0
        self.requests = 0
        self.failures = 0

        # factory for the local stand-in, and the stand-in once it has been needed
        self.fallback_factory = fallback
        self.fallback = None

        self.monitor = Monitor(sensor, self.knowledge, log=log)
        self.executor = Executor(effector, self.knowledge, log=log)

    # whether this step is one the loop runs on
    def due(self, step):
        return step % self.period == 0

    # one turn of the loop. Unlike the local one there is no short circuit for a quiet step: deciding that
    # nothing needs doing is the server's job, so it is sent the snapshot and answers with no directives.
    def tick(self, step):
        if not self.due(step):
            return None

        self.evaluations += 1
        snapshot = self.monitor.observe()
        allocation = self.consult(snapshot)

        if allocation is None or not allocation.directives:
            return None

        self.executor.execute(allocation)
        return allocation

    # asks the server what the team should be flying, falling back when it cannot answer
    def consult(self, snapshot):
        payload = {"session": self.session, "step": snapshot.step, "snapshot": snapshot.to_json()}
        self.requests += 1

        try:
            raw = self.transport(self.url, payload, self.timeout)
            allocation = Allocation.from_json(json.loads(raw))
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
            # every way a server can let us down lands here: refused, timed out, an error status, a body
            # that is not JSON, and JSON that is not an allocation
            self.failures += 1
            return self.fall_back(snapshot, exc)

        # the step is stamped from the snapshot rather than taken from the response, so that a server that
        # echoes the wrong one, or none, cannot make the run's own record of when it adapted wrong
        return Allocation(step=snapshot.step, directives=allocation.directives,
                          rationale=allocation.rationale or f"remote plan from {self.url}")

    # decides what to do about an evaluation the server could not answer
    def fall_back(self, snapshot, exc):
        if self.log is not None:
            self.log.warning("remote managing system at %s failed (%s: %s), %s",
                             self.url, type(exc).__name__, exc,
                             "standing in locally" if self.fallback_factory is not None
                             else "leaving the allocation unchanged")

        if self.fallback_factory is None:
            return None

        # built on first need and kept, so that a server which stays down does not cost a rebuild per step
        # and the stand-in accumulates the history its hysteresis depends on
        if self.fallback is None:
            self.fallback = self.fallback_factory()

        allocation = self.fallback.decide(snapshot)
        if allocation is None:
            return None
        return allocation.because(f"{allocation.rationale} [remote managing system unreachable]")

    # how many times the allocation has actually changed over the run, which the status panel reports
    def adaptations(self):
        return self.knowledge.adaptations

    def __str__(self):
        return f"remote MAPE-K at {self.url}, every {self.period} step(s)"
