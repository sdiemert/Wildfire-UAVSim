"""One simulation, start to finish.

RunConfig is everything a worker needs to execute a run and RunResult is everything it reports back; both
are plain dataclasses so that they survive being pickled across a process pool.
"""

from __future__ import annotations

# python libraries

import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

# own python modules

from sim.cli.overrides import _import_simulation, apply_overrides, seed_simulation
from sim.cli.reporting import LOGGER_NAME, _LogWriter, _mean


@dataclass
class RunConfig:
    """Everything a worker needs to execute one simulation."""

    run_id: int
    # how many steps to run, which is always the run's BATCH_SIZE: headless.py resolves --steps and
    # --set BATCH_SIZE into one number before building this, because a loop bound that disagreed with
    # the constant the model stops on is exactly how a run length gets silently ignored
    steps: int
    seed: int | None = None
    overrides: dict[str, Any] = field(default_factory=dict)
    log_every: int = 10
    # policy name, resolved to an instance inside the worker; a plain string keeps RunConfig picklable
    policy: str = "random"
    # MAPE-K components overriding those of the selected managing system, as {role: name}. These are not
    # settings in config.py -- they name registered components -- so they travel here rather than in
    # 'overrides'. Empty means the managing system runs as it is registered.
    managing_components: dict[str, str] = field(default_factory=dict)


@dataclass
class RunResult:
    """Outcome of one simulation."""

    run_id: int
    seed: int | None
    steps_completed: int
    wall_time_s: float
    mr1_per_uav: list[float] = field(default_factory=list)
    mr1_total: float = 0.0
    mr2: int = 0
    # UAV collisions: cells found holding more than one UAV, and UAVs destroyed by them
    collisions: int = 0
    uavs_lost: int = 0
    # fuel extension; zero/empty when it is switched off. uavs_out_of_fuel is the share of uavs_lost
    # above that ran dry rather than being destroyed in a collision, and fuel_remaining is what each UAV
    # of the team had left at the end, in team order, a destroyed one keeping whatever it died with.
    uavs_out_of_fuel: int = 0
    fuel_remaining: list[float] = field(default_factory=list)
    burning_cells_final: int = 0
    burned_out_cells_final: int = 0
    # where and when the fire was lit; worth recording because both can be randomised in config.py
    fire_start_pos: list[int] = field(default_factory=list)
    fire_start_step: int = 0
    # firefighting extension; all zero/false when it is switched off
    water_drops: int = 0
    cells_extinguished: int = 0
    refills: int = 0
    # out buildings destroyed, of the ones that were placed; buildings_total is 0 when none were configured
    buildings_lost: int = 0
    buildings_total: int = 0
    base_burning_steps: int = 0
    # whether the run had a base to lose at all, which is what makes 'lost' meaningful
    firefighting: bool = False
    lost: bool = False
    # managing system (MAPE-K); all zero/empty when MANAGING_SYSTEM is 'none', which is what makes an
    # A/B against the unmanaged simulation a matter of one setting
    managing: bool = False
    # which managing system ran, and where it lived ('none', 'local' or 'remote'). Both are recorded
    # because the name is the arm of the experiment and the location is how the result was produced.
    managing_system: str = "none"
    managing_location: str = "none"
    # which component did each of the five MAPE-K jobs. Empty for an unmanaged run, and for a remote one,
    # whose components are the server's and are not reported to this side.
    managing_components: dict[str, str] = field(default_factory=dict)
    # how many times the allocation actually changed over the run
    adaptations: int = 0
    # how many UAV-steps were flown under each policy, which is what says whether the managing system
    # actually used the policies it was given or settled on one and stayed there
    policy_steps: dict[str, int] = field(default_factory=dict)
    # what each UAV was flying when the run ended, keyed by unique id as a string so the JSON survives
    allocation_final: dict[str, str] = field(default_factory=dict)
    # directives the effector refused, and evaluations a remote managing system could not answer. Both
    # are zero on a healthy run; either being non zero means the result was produced with less managing
    # than was asked for, which a reader has to know before comparing it with anything
    directives_rejected: int = 0
    managing_failures: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def outcome(self) -> str:
        """WON or LOST, or N/A for a run with no home base to lose."""
        if not self.firefighting:
            return "N/A"
        return "LOST" if self.lost else "WON"


def _count_fire_cells(model) -> tuple[int, int]:
    """Return (burning cells, burned out cells) for the current grid state."""
    burning = 0
    burned_out = 0
    # model.fire_list is every Fire agent, which saves picking them back out of the scheduler
    for agent in model.fire_list:
        if agent.is_burning():
            burning += 1
        if agent.get_fuel() <= 0:
            burned_out += 1
    return burning, burned_out


def run_simulation(config: RunConfig) -> RunResult:
    """Execute one simulation to completion and return its metrics."""
    log = logging.getLogger(f"{LOGGER_NAME}.run{config.run_id:03d}")
    started = time.perf_counter()

    try:
        cfg, wildfire_model, agents, policy_module = _import_simulation()

        if config.overrides:
            apply_overrides(config.overrides)
            log.info("overrides applied: %s", config.overrides)
        if config.seed is not None:
            seed_simulation(config.seed)

        policy = policy_module.build_policy(config.policy)

        log.info(
            "starting: %d steps, %dx%d grid, %d UAVs, policy=%s, managing=%s, seed=%s",
            config.steps,
            cfg.HEIGHT,
            cfg.WIDTH,
            cfg.NUM_AGENTS,
            policy,
            cfg.MANAGING_SYSTEM,
            config.seed,
        )

        # the model prints to stdout on construction; route that into the log.
        # passing 'log' gives the model and its agents this run's logger, so agent level
        # messages are tagged with the run they belong to.
        #
        # AdaptiveWildFireModel is the plain WildFireModel with one turn of the MAPE-K loop in front of
        # its step(). With MANAGING_SYSTEM 'none' it builds no sensor and no effector and behaves exactly
        # as the model it subclasses, so one runner covers both arms of an A/B experiment.
        from sim.adaptive import AdaptiveWildFireModel

        with contextlib.redirect_stdout(_LogWriter(log)):
            model = AdaptiveWildFireModel(log=log, policy=policy,
                                          components=config.managing_components)

        # UAV-steps flown under each policy, sampled once per step. Counted here rather than derived from
        # the allocations because a UAV goes on flying its last allocation over the steps the loop does
        # not run on, and it is the flying that the result is about.
        policy_steps: dict[str, int] = {}

        steps_completed = 0
        for step in range(1, config.steps + 1):
            try:
                with contextlib.redirect_stdout(_LogWriter(log)):
                    model.step()
            except SystemExit:
                # defensive: nothing in the model calls sys.exit() any more, but a
                # policy or a future change might.
                log.info("model requested exit at step %d", step)
                break

            steps_completed = step

            for uav_id, name in model.allocation().items():
                if model.uav_by_id(uav_id) is not None and model.uav_by_id(uav_id).is_alive():
                    policy_steps[name] = policy_steps.get(name, 0) + 1

            # the model clears 'running' when it reaches its own BATCH_SIZE, and when the home base is
            # destroyed. config.steps is that same BATCH_SIZE -- headless.py folds --steps into the
            # overrides rather than counting separately -- so the first case is how a full length run
            # ends, on the last step this loop would have run anyway. The loop bound is kept as a
            # backstop, so a model that never clears 'running' cannot spin here forever.
            if not model.running:
                # a lost run has already logged why it stopped, and reports it again below
                if not model.lost:
                    log.info("model stopped itself at step %d (BATCH_SIZE reached)", step)
                break

            if config.log_every and step % config.log_every == 0:
                burning, burned_out = _count_fire_cells(model)
                log.info(
                    "step %3d/%d | burning=%4d burned_out=%4d | MR1_mean=%.4f MR2=%d",
                    step,
                    config.steps,
                    burning,
                    burned_out,
                    sum(model.MR1_LIST) / len(model.MR1_LIST) if model.MR1_LIST else 0.0,
                    model.MR2_VALUE,
                )

        burning, burned_out = _count_fire_cells(model)
        elapsed = time.perf_counter() - started

        result = RunResult(
            run_id=config.run_id,
            seed=config.seed,
            steps_completed=steps_completed,
            wall_time_s=round(elapsed, 3),
            mr1_per_uav=[round(value, 6) for value in model.MR1_LIST],
            mr1_total=round(sum(model.MR1_LIST), 6),
            mr2=model.MR2_VALUE,
            collisions=model.collisions,
            uavs_lost=model.uavs_lost,
            uavs_out_of_fuel=model.uavs_out_of_fuel,
            fuel_remaining=[round(uav.fuel, 3) for uav in model.uavs] if cfg.ACTIVATE_FUEL else [],
            burning_cells_final=burning,
            burned_out_cells_final=burned_out,
            fire_start_pos=list(model.fire_start_pos),
            fire_start_step=model.fire_start_step,
            water_drops=model.water_drops,
            cells_extinguished=model.cells_extinguished,
            refills=model.refills,
            buildings_lost=model.buildings_lost,
            buildings_total=len(model.out_buildings),
            base_burning_steps=model.base.burning_steps if model.base is not None else 0,
            firefighting=cfg.ACTIVATE_FIREFIGHTING,
            lost=model.lost,
            managing=model.managing is not None,
            managing_system=model.managing_kind,
            managing_location=model.managing_location,
            managing_components=model.composition(),
            adaptations=model.adaptations(),
            policy_steps=policy_steps,
            allocation_final={str(uav_id): name for uav_id, name in model.allocation().items()},
            directives_rejected=model.effector.rejected if model.effector is not None else 0,
            managing_failures=getattr(model.managing, "failures", 0) if model.managing else 0,
        )
        log.info(
            "finished in %.2fs | fire at %s from step %d | MR1_total=%.4f MR2=%d burning=%d "
            "| collisions=%d UAVs_lost=%d/%d",
            elapsed,
            tuple(result.fire_start_pos),
            result.fire_start_step,
            result.mr1_total,
            result.mr2,
            result.burning_cells_final,
            result.collisions,
            result.uavs_lost,
            len(model.uavs),
        )
        if cfg.ACTIVATE_FUEL:
            log.info(
                "fuel | ran dry=%d/%d | tanks left: mean=%.1f min=%.1f of %.0f",
                result.uavs_out_of_fuel, len(model.uavs),
                _mean(result.fuel_remaining), min(result.fuel_remaining, default=0.0), cfg.UAV_FUEL,
            )
        if cfg.ACTIVATE_FIREFIGHTING:
            log.info(
                "firefighting | drops=%d extinguished=%d refills=%d%s",
                result.water_drops, result.cells_extinguished, result.refills,
                # out buildings are optional within the extension, so they are only mentioned
                # when NUM_OUT_BUILDINGS actually put some on the map
                f" | out buildings destroyed={result.buildings_lost}/{result.buildings_total}"
                if result.buildings_total else "",
            )
            log.info(
                "RUN %s | home base burned %d/%d step(s)",
                result.outcome, result.base_burning_steps, cfg.BHP,
            )
        if result.managing:
            log.info(
                "managing | %s adaptations=%d | UAV-steps: %s%s",
                # the composition is named as well as the system, because --mape can have made this run a
                # combination that no registered system describes
                f"{result.managing_system} ({result.managing_location})" + (
                    " " + " ".join(f"{role[0].upper()}={name}"
                                   for role, name in result.managing_components.items())
                    if result.managing_components else ""),
                result.adaptations,
                ", ".join(f"{name}={count}" for name, count in sorted(result.policy_steps.items()))
                or "none",
                # both are silent on a healthy run, and both change how the result should be read
                (f" | REFUSED {result.directives_rejected} directive(s)"
                 if result.directives_rejected else "")
                + (f" | managing system unreachable {result.managing_failures} time(s)"
                   if result.managing_failures else ""),
            )
        return result

    except Exception as exc:  # noqa: BLE001 - a failed run must not kill the batch
        elapsed = time.perf_counter() - started
        log.exception("run failed after %.2fs: %s", elapsed, exc)
        return RunResult(
            run_id=config.run_id,
            seed=config.seed,
            steps_completed=0,
            wall_time_s=round(elapsed, 3),
            error=f"{type(exc).__name__}: {exc}",
        )
