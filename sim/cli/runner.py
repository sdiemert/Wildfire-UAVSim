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
    steps: int
    seed: int | None = None
    overrides: dict[str, Any] = field(default_factory=dict)
    log_every: int = 10
    # policy name, resolved to an instance inside the worker; a plain string keeps RunConfig picklable
    policy: str = "random"


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
            "starting: %d steps, %dx%d grid, %d UAVs, policy=%s, seed=%s",
            config.steps,
            cfg.HEIGHT,
            cfg.WIDTH,
            cfg.NUM_AGENTS,
            policy,
            config.seed,
        )

        # the model prints to stdout on construction; route that into the log.
        # passing 'log' gives the model and its agents this run's logger, so agent level
        # messages are tagged with the run they belong to.
        with contextlib.redirect_stdout(_LogWriter(log)):
            model = wildfire_model.WildFireModel(log=log, policy=policy)

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

            # the model clears 'running' when it reaches its own BATCH_SIZE, and when the home
            # base is destroyed. The BATCH_SIZE case normally does not arise, because this loop
            # stops first unless --steps is larger than it.
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
