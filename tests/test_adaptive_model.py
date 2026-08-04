"""End to end tests for the self-adaptive model.

The two that matter most are at the bottom: that switching the managing system off reproduces the plain
simulation exactly, and that switching it on actually achieves what it exists for. Everything above them is
the wiring those two depend on.
"""

# python libraries

import random

import pytest

# own python modules

import config

from sim.managing.contract import Allocation, UavDirective
from sim.managing.plan.base import Planner
from sim.model import WildFireModel
from sim.policy import SuperPolicy


@pytest.fixture
def adaptive(sim_config):
    """Builds an AdaptiveWildFireModel on a small grid, with the managing system on by default.

    Named arguments go to the model as the web interface passes them; anything else is a config override,
    the same split as the `make_model` fixture uses.

    Usage:
        adaptive(NUM_AGENTS=6)                            # config overrides
        adaptive(MANAGING_SYSTEM="none", managing="heuristic")  # ... and a per model override
    """

    def _make(policy=None, managing=None, url=None, **overrides):
        settings = {"WIDTH": 20, "HEIGHT": 20, "NUM_AGENTS": 4, "BATCH_SIZE": 10_000,
                    "DENSITY_PROB": 1.0, "FIRE_START_POSITION": None, "FIRE_START_STEP": 0,
                    "MANAGING_SYSTEM": "heuristic", "ACTIVATE_FIREFIGHTING": True,
                    "ADAPTATION_HYSTERESIS": 1}
        settings.update(overrides)
        sim_config(**settings)

        from sim.adaptive import AdaptiveWildFireModel

        return AdaptiveWildFireModel(policy=policy, managing=managing, url=url)

    return _make


# --- wiring -----------------------------------------------------------------


def test_the_managing_system_is_built_when_one_is_asked_for(adaptive):
    model = adaptive()
    assert model.managing is not None
    assert model.sensor is not None and model.effector is not None
    assert isinstance(model.policy, SuperPolicy)


def test_nothing_is_built_for_none(adaptive):
    model = adaptive(MANAGING_SYSTEM="none")
    assert model.managing is None
    assert model.sensor is None and model.effector is None
    assert not isinstance(model.policy, SuperPolicy)


# --- the managing system can be switched per model ---------------------------


def test_the_web_interface_can_start_a_managing_system(adaptive):
    """config.py says none, the dropdown says heuristic: the dropdown wins, for this model alone."""
    model = adaptive(MANAGING_SYSTEM="none", managing="heuristic")
    assert model.managing is not None
    assert model.managing_kind == "heuristic"
    # and the configuration is left exactly as it was, so the next model built is unaffected
    assert config.MANAGING_SYSTEM == "none"


def test_the_web_interface_can_stop_the_managing_system(adaptive):
    model = adaptive(MANAGING_SYSTEM="heuristic", managing="none")
    assert model.managing is None
    assert model.managing_kind == "none"
    assert config.MANAGING_SYSTEM == "heuristic"


def test_the_web_interface_can_move_it_to_a_server(adaptive):
    from sim.managing.remote import RemoteManagingSystem

    model = adaptive(MANAGING_SYSTEM="heuristic", managing="remote", url="http://server/manage")
    assert isinstance(model.managing, RemoteManagingSystem)
    assert model.managing.url == "http://server/manage"
    assert config.MANAGING_SYSTEM == "heuristic"


def test_without_an_override_the_configuration_decides(adaptive):
    assert adaptive(MANAGING_SYSTEM="heuristic").managing is not None
    assert adaptive(MANAGING_SYSTEM="none").managing is None


@pytest.mark.parametrize("value, kind", [
    ("none", "none"), ("heuristic", "heuristic"), ("remote", "remote"), ("static", "static"),
    ("HEURISTIC", "heuristic"), (" none ", "none"),
    (True, "heuristic"), (False, "none"),
    # 'local' is what the default managing system was called when there was only one of them
    ("local", "heuristic"),
])
def test_the_dropdown_value_is_understood(adaptive, value, kind):
    # mesa hands a Choice over as a string; booleans are accepted for callers in python. An alias is
    # reported under the name of what actually ran, not under the name it was asked for.
    assert adaptive(managing=value).managing_kind == kind


def test_an_unknown_managing_system_is_refused(adaptive):
    with pytest.raises(KeyError, match="available"):
        adaptive(managing="telepathy")


# the managing settings are only checked by config.validate() when the configuration asks for a managing
# system. Starting one from the web interface has to get them checked anyway, or a run started there would
# skip bounds a headless one enforces.
def test_starting_one_validates_the_managing_settings(adaptive):
    with pytest.raises(ValueError, match="ADAPTATION_PERIOD"):
        adaptive(MANAGING_SYSTEM="none", ADAPTATION_PERIOD=0, managing="heuristic")


def test_stopping_it_ignores_the_managing_settings(adaptive):
    # nothing reads them, so a nonsense value must not stop an unmanaged run from starting
    assert adaptive(MANAGING_SYSTEM="none", ADAPTATION_PERIOD=0, managing="none") is not None


def test_a_model_without_one_is_the_plain_simulation(adaptive):
    model = adaptive(MANAGING_SYSTEM="heuristic", managing="none")
    assert model.sensor is None and model.effector is None
    assert not isinstance(model.policy, SuperPolicy)
    assert model.allocation() == {} and model.adaptations() == 0 and model.rationale() == ""
    assert model.managing_enabled is False


def test_a_model_without_one_still_steps(adaptive):
    model = adaptive(MANAGING_SYSTEM="heuristic", managing="none")
    for _ in range(5):
        model.step()
    assert model.evaluation_timesteps_counter == 5


def test_the_team_starts_on_the_policy_it_was_given(adaptive, sim_config):
    sim_config(MANAGING_SYSTEM="heuristic")
    from sim.adaptive import AdaptiveWildFireModel

    sim_config(WIDTH=20, HEIGHT=20, NUM_AGENTS=2, DENSITY_PROB=1.0,
               FIRE_START_POSITION=None, FIRE_START_STEP=0, ACTIVATE_FIREFIGHTING=True)
    model = AdaptiveWildFireModel(policy="follow-fire")
    assert model.policy.default == "follow-fire"


def test_an_unknown_bootstrap_policy_is_reported_at_build_time(adaptive, sim_config):
    with pytest.raises(KeyError, match="firefighter"):
        adaptive(DEFAULT_UAV_POLICY="no-such-policy")


# --- the loop drives the run ------------------------------------------------


def test_the_loop_runs_before_each_step(adaptive):
    model = adaptive()
    for _ in range(5):
        model.step()
    assert model.managing.evaluations == 5


def test_the_adaptation_period_is_honoured(adaptive):
    model = adaptive(ADAPTATION_PERIOD=3)
    for _ in range(9):
        model.step()
    assert model.managing.evaluations == 3


def test_the_allocation_reaches_the_uavs(adaptive):
    class SendsEveryoneToDisperse(Planner):
        name = "test"

        def plan(self, snapshot, symptoms, knowledge):
            return Allocation(step=snapshot.step, rationale="test",
                              directives=tuple(UavDirective(report.uav_id, "disperse")
                                               for report in snapshot.alive()))

    model = adaptive()
    model.managing.planner = SendsEveryoneToDisperse()
    # something has to be wrong for the loop to reach Plan at all, so light the base's neighbourhood
    for _ in range(6):
        model.step()

    assert set(model.allocation().values()) == {"disperse"}


def test_the_model_reports_what_it_is_doing(adaptive):
    model = adaptive()
    for _ in range(6):
        model.step()
    assert isinstance(model.adaptations(), int)
    assert isinstance(model.allocation(), dict)
    assert isinstance(model.rationale(), str)


def test_a_plain_model_reports_no_managing_system(make_model):
    model = make_model(policy="random")
    # the sidebar and the runner ask these of any model, so they have to be answerable for both
    assert getattr(model, "managing", None) is None


# --- it does not break the simulation ---------------------------------------


def test_a_managed_run_finishes(adaptive):
    model = adaptive(BATCH_SIZE=40)
    for _ in range(40):
        model.step()
        if not model.running:
            break
    assert model.evaluation_timesteps_counter > 0


def test_a_managed_run_is_reproducible(adaptive):
    def run(seed):
        config.SYSTEM_RANDOM = random.Random(seed)
        random.seed(seed)
        model = adaptive(BATCH_SIZE=30)
        for _ in range(30):
            model.step()
            if not model.running:
                break
        return (model.evaluation_timesteps_counter, model.collisions, model.uavs_lost,
                model.adaptations(), sorted(model.allocation().items()))

    assert run(11) == run(11)


def test_destroying_a_uav_mid_run_does_not_upset_the_loop(adaptive):
    model = adaptive()
    model.step()

    doomed = model.uavs[0]
    doomed.take_damage(config.UAV_HP)
    model.destroy_uav(doomed)

    for _ in range(5):
        model.step()          # must not raise
    assert doomed.unique_id not in {uav.unique_id for uav in model.active_uavs()}


def test_a_team_of_no_uavs_is_managed_without_incident(adaptive):
    model = adaptive(NUM_AGENTS=0)
    for _ in range(5):
        model.step()
    assert model.allocation() == {}


# --- the two that matter ----------------------------------------------------


def test_switching_the_managing_system_off_reproduces_the_plain_model(sim_config):
    """With MANAGING_SYSTEM 'none', the adaptive model must be the simulation as it always was."""
    from sim.adaptive import AdaptiveWildFireModel

    settings = dict(WIDTH=20, HEIGHT=20, NUM_AGENTS=4, BATCH_SIZE=10_000, DENSITY_PROB=1.0,
                    FIRE_START_POSITION=None, FIRE_START_STEP=0, ACTIVATE_FIREFIGHTING=True,
                    MANAGING_SYSTEM="none")

    def run(model_class):
        config.SYSTEM_RANDOM = random.Random(4)
        random.seed(4)
        sim_config(**settings)
        model = model_class(policy="firefighter")
        for _ in range(25):
            model.step()
        return ([uav.pos for uav in model.uavs], model.collisions, model.uavs_lost,
                model.water_drops, model.cells_extinguished, round(sum(model.MR1_LIST), 6),
                model.MR2_VALUE)

    assert run(AdaptiveWildFireModel) == run(WildFireModel)


def test_the_managing_system_keeps_uavs_from_colliding(sim_config):
    """What the managing system exists for, measured rather than asserted.

    A team on `follow-fire` has no team level deconfliction at all: it flies its UAVs into each other and
    loses most of them. The same team under the managing system should not.
    """
    from sim.adaptive import AdaptiveWildFireModel

    def run(seed, managing):
        config.SYSTEM_RANDOM = random.Random(seed)
        random.seed(seed)
        sim_config(WIDTH=20, HEIGHT=20, NUM_AGENTS=8, BATCH_SIZE=10_000, DENSITY_PROB=0.9,
                   FIRE_START_POSITION=None, FIRE_START_STEP=5, ACTIVATE_FIREFIGHTING=True,
                   MANAGING_SYSTEM=managing, DEFAULT_UAV_POLICY="follow-fire")
        model = AdaptiveWildFireModel(policy="follow-fire")
        for _ in range(60):
            model.step()
            if not model.running:
                break
        return model

    unmanaged = [run(seed, "none") for seed in range(6)]
    managed = [run(seed, "heuristic") for seed in range(6)]

    unmanaged_collisions = sum(model.collisions for model in unmanaged)
    managed_collisions = sum(model.collisions for model in managed)

    assert unmanaged_collisions > 0, "the baseline has to actually collide for this to measure anything"
    assert managed_collisions < unmanaged_collisions, (
        f"managed runs collided {managed_collisions} time(s) against the baseline's "
        f"{unmanaged_collisions}")
    assert sum(m.uavs_lost for m in managed) < sum(m.uavs_lost for m in unmanaged)
