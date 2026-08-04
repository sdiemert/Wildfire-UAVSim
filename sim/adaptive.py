"""The self-adaptive model: a WildFireModel with a managing system over it.

This is the composition root. It is the one place that knows about both halves, and all it does is build
them and decide the order they run in. WildFireModel itself is untouched and unaware: it still holds one
Policy and calls select_actions() on it once a step, exactly as it always did, and everything the managing
system does reaches it through that policy being a SuperPolicy whose table somebody else is writing.

The obvious alternative -- driving the loop from the runner, outside the model -- is cleaner still, and is
what sim/cli/ would do on its own. It does not survive contact with the web interface: mesa's ModularServer
owns the run loop and calls model.step() directly, so there is no outer loop to hang a managing system off.
Subclassing gives both the runner and the server the same behaviour for free, and costs only that the
sequencing lives in a subclass rather than in a caller. The dependency still points the right way: this
module imports the managing system, and the managing system imports nothing from here.
"""

# own python modules

import config

from sim.adapters import AllocationEffector, ModelSensor
# aliased, because 'managing_system' is also the name of this class's argument for a prebuilt loop
from sim.managing.systems import build_managing_system, managing_system as managing_spec
from sim.model import WildFireModel
from sim.policy import SuperPolicy


class AdaptiveWildFireModel(WildFireModel):
    """WildFireModel, plus a MAPE-K loop that reallocates policies as the run goes.

    With MANAGING_SYSTEM set to 'none' this is the plain simulation, down to the last detail: the model is
    built with whatever single policy it was given, no sensor or effector is created, and step() does
    nothing but call its parent. That is what makes an A/B comparison between the managed and the
    self-adaptive system a matter of one setting.

    With it set to any of the managing systems registered in sim/managing/systems.py, the team flies a
    SuperPolicy instead and that managing system decides what each UAV is on. This class builds the same
    sensor and effector whichever one it is, and whether it runs here or on a server, because they are the
    simulation's own interface and belong here whatever is doing the deciding.

    The 'policy' argument then names the policy every UAV *starts* under, before the first evaluation, and
    the managing system reallocates from there. What an unallocated UAV falls back to inside the local
    planner is DEFAULT_UAV_POLICY, which is a separate setting for a separate question: one is where the
    run begins, the other is what the planner considers normal.
    """

    # constructor. 'managing' and 'url' override MANAGING_SYSTEM and MANAGING_SYSTEM_URL for this model
    # alone, which is what the web interface dropdown and the --managing option hand in, and 'components'
    # overrides individual MAPE-K components of whichever managing system that names, which is what --mape
    # hands in. 'managing_system' injects a prebuilt loop instead of building one, which is for tests.
    #
    # The overrides are held on the instance and never written back to config, so that pressing Reset on
    # the web interface with a different setting builds a different model rather than quietly changing the
    # configuration for everything built afterwards -- and so that the runner's worker processes, which do
    # apply their overrides to config, are unaffected by any of this.
    def __init__(self, log=None, policy=None, managing=None, url=None, components=None,
                 managing_system=None):
        self.managing = None
        self.sensor = None
        self.effector = None
        self.managing_kind = self.resolve_managing(managing)
        self.managing_components = dict(components or {})

        if self.managing_kind == "none":
            # nothing to manage with: behave exactly as the plain model does
            super().__init__(log=log, policy=policy)
            return

        # the bootstrap policy: what the team flies until the first evaluation says otherwise
        bootstrap = self.bootstrap_policy(policy)
        super_policy = SuperPolicy(default=bootstrap)
        super().__init__(log=log, policy=super_policy)

        # the two ends of the sensor/effector contract, built over the model that now exists. They are the
        # same whether the managing system is here or on a server: what changes is only who they talk to.
        self.sensor = ModelSensor(self, super_policy)
        self.effector = AllocationEffector(super_policy, self, log=self.log)
        self.managing = managing_system if managing_system is not None else build_managing_system(
            sensor=self.sensor, effector=self.effector, managing=self.managing_kind,
            components=self.managing_components, url=url, log=self.log,
        )

        self.log.info("managing system ready: %s, UAVs start on %s", self.managing, bootstrap)

    # decides which managing system this model runs, by name. None defers to MANAGING_SYSTEM; anything else
    # overrides it for this model alone. The web interface hands its dropdown over as a string, and
    # booleans are accepted so that a caller in python can say True/False without knowing the names.
    #
    # The name is resolved through the registry rather than merely checked, so that an alias is reported
    # under the name of what actually ran: --managing local produces a model that says 'heuristic'.
    def resolve_managing(self, managing):
        if isinstance(managing, bool):
            managing = "heuristic" if managing else "none"
        elif managing is None:
            managing = config.MANAGING_SYSTEM

        return managing_spec(str(managing).strip().lower()).name

    # whether this model has a managing system at all, which the runner and the interface ask
    @property
    def managing_enabled(self):
        return self.managing_kind != "none"

    # where the managing system runs: 'none', 'local' or 'remote'. Reported alongside its name, because the
    # name says which managing system is running and this says whether the deciding happens in this process.
    @property
    def managing_location(self):
        return getattr(self.managing, "location", "none")

    # which component is doing each of the five MAPE-K jobs, as {role: name}. Empty when there is no
    # managing system, and empty for a remote one, whose components are the server's.
    #
    # Both of these are read through getattr because they are reported from inside mesa's render loop,
    # where an AttributeError does not surface as a failed test but as a dead websocket and a simulation
    # that silently stops. A managing system injected by a test is not obliged to have either.
    def composition(self):
        composition = getattr(self.managing, "composition", None)
        return dict(composition()) if composition is not None else {}

    # resolves the policy the team starts under. A name or an instance is accepted, the same way
    # WildFireModel accepts them, because the web interface hands its dropdown selection over as a string.
    def bootstrap_policy(self, policy):
        if policy is None:
            return config.DEFAULT_UAV_POLICY
        if isinstance(policy, str):
            return policy
        # an instance was passed; SuperPolicy builds its own, so only the name is kept
        return policy.name

    # one simulation step, with one turn of the MAPE-K loop in front of it.
    #
    # The order matters and is the whole of what this class decides. The loop observes the state left by
    # the previous step and writes an allocation; the step that follows is flown under it. So the managing
    # system always acts on a settled world rather than reaching into the middle of one, and an adaptation
    # takes effect on the step after the reading that prompted it -- which is what a real managing system,
    # working from telemetry it has already received, would have to live with too.
    def step(self):
        if self.managing is not None and self.running:
            self.managing.tick(self.evaluation_timesteps_counter)
        super().step()

    # how many times the allocation has actually changed, which the runner reports and the status panel
    # shows. Zero when the managing system is switched off.
    def adaptations(self):
        return 0 if self.managing is None else self.managing.adaptations()

    # what each UAV is flying right now, as {uav id: policy name}. Empty when there is no managing system.
    #
    # Every UAV of the team is reported, not only the ones that have been allocated something: until the
    # first adaptation the assignment table is empty and the whole team is flying the bootstrap policy, so
    # reading the table alone says the team is flying nothing at all. That made the status panel blank for
    # the opening steps of every run, and left those steps out of the runner's policy_steps -- which is a
    # count of what was actually flown, and so has to include the steps before anything was reallocated.
    def allocation(self):
        if not isinstance(self.policy, SuperPolicy):
            return {}
        return {uav.unique_id: self.policy.allocated(uav.unique_id)[0] for uav in self.uavs}

    # the last thing the planner said about why, shown on the status panel
    def rationale(self):
        return "" if self.managing is None else self.managing.knowledge.rationale
