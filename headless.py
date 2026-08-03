#!/usr/bin/env python3
"""Headless runner for the wildfire UAV simulation.

Runs WildFireModel without the Mesa visualization server, logs progress through
the standard logging module, and can execute several independent simulations in
parallel.

Examples:

    # single run, default parameters from config.py
    python3 headless.py

    # 20 runs on 4 worker processes, results written to disk
    python3 headless.py --runs 20 --workers 4 --output results.json

    # override simulation constants, log every step
    python3 headless.py --set NUM_AGENTS=4 --set ACTIVATE_WIND=True --log-every 1
"""

from __future__ import annotations

# python libraries

import argparse
import ast
import contextlib
import json
import logging
import logging.handlers
import multiprocessing
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Any

LOGGER_NAME = "wildfire"
LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"

# queue used by worker processes to ship log records back to the parent
_LOG_QUEUE: Any = None


# ---------------------------------------------------------------------------
# configuration / results
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# simulation module plumbing
# ---------------------------------------------------------------------------


def _import_simulation():
    """Import the simulation modules.

    Returned as a tuple so that apply_overrides() and seed_simulation() can walk
    them. The simulation itself is headless: nothing in it imports matplotlib,
    so there is no GUI backend to force here.
    """
    import agents
    import config as cfg
    import wildfire_model
    from sim import policy

    return cfg, wildfire_model, agents, policy


def apply_overrides(overrides: dict[str, Any]) -> None:
    """Override simulation constants.

    Every module reads its settings through `config.` at the point of use, so
    setting them on config alone reaches the whole simulation. (This used to
    have to walk every module: `from config import *` had copied the values
    into each of their namespaces, and patching config reached none of them.)
    """
    if not overrides:
        return

    cfg = _import_simulation()[0]

    for name, value in overrides.items():
        if not hasattr(cfg, name):
            raise KeyError(f"unknown simulation constant: {name}")
        setattr(cfg, name, value)

    # derived constants that would otherwise keep their original values
    if "UAV_OBSERVATION_RADIUS" in overrides:
        cfg.side = (overrides["UAV_OBSERVATION_RADIUS"] * 2) + 1
        cfg.N_OBSERVATIONS = cfg.side * cfg.side

    # the overrides are checked together with everything they did not touch, so that a combination which
    # is only invalid once applied (say NUM_AGENTS raised above WIDTH * HEIGHT) is caught here, before any
    # worker starts a run with it
    cfg.validate()


def seed_simulation(seed: int) -> None:
    """Seed every random source the simulation uses.

    Everything stochastic in the simulation draws from SYSTEM_RANDOM: cell fuel,
    tree placement, the fire spread rolls, UAV actions and policy tie breaks.
    It is a random.SystemRandom instance, which cannot be seeded, so it is
    replaced by a seeded random.Random. Every module reads config.SYSTEM_RANDOM
    at the point of use, so setting it on config reaches all of them.

    The `random` module is seeded as well. Nothing in the simulation draws from
    it any more, but mesa.Model builds its own random.Random from it, so seeding
    keeps anything reached through mesa reproducible too.
    """
    random.seed(seed)
    _import_simulation()[0].SYSTEM_RANDOM = random.Random(seed)


class _LogWriter:
    """File-like object that forwards writes to a logger, one line per record."""

    def __init__(self, log: logging.Logger, level: int = logging.DEBUG):
        self._log = log
        self._level = level
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._log.log(self._level, "stdout: %s", line.strip())
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self._log.log(self._level, "stdout: %s", self._buffer.strip())
        self._buffer = ""


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


# ---------------------------------------------------------------------------
# the simulation loop
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# logging setup
# ---------------------------------------------------------------------------


def configure_logging(level: str, log_file: str | None) -> logging.Logger:
    """Configure the parent process logger."""
    log = logging.getLogger(LOGGER_NAME)
    log.setLevel(getattr(logging, level.upper()))
    log.propagate = False
    log.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT, datefmt="%H:%M:%S")

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    log.addHandler(stream_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file, mode="w")
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        log.addHandler(file_handler)

    return log


def _worker_init(queue, level: str) -> None:
    """Initializer for pool workers: send all log records to the parent."""
    global _LOG_QUEUE
    _LOG_QUEUE = queue

    log = logging.getLogger(LOGGER_NAME)
    log.setLevel(getattr(logging, level.upper()))
    log.propagate = False
    log.handlers.clear()
    log.addHandler(logging.handlers.QueueHandler(queue))


# ---------------------------------------------------------------------------
# batch execution
# ---------------------------------------------------------------------------


def run_batch(
    configs: list[RunConfig],
    workers: int,
    executor_kind: str,
    log_level: str,
    log: logging.Logger,
) -> list[RunResult]:
    """Run every configuration, in parallel when workers > 1."""
    if workers <= 1 or len(configs) == 1:
        log.info("running %d simulation(s) sequentially", len(configs))
        return [run_simulation(config) for config in configs]

    results: list[RunResult] = []

    if executor_kind == "thread":
        log.info("running %d simulation(s) on %d threads", len(configs), workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_simulation, c): c for c in configs}
            results = _collect(futures, log)
    else:
        log.info("running %d simulation(s) on %d processes", len(configs), workers)
        manager = multiprocessing.Manager()
        queue = manager.Queue()
        listener = logging.handlers.QueueListener(
            queue, *log.handlers, respect_handler_level=True
        )
        listener.start()
        try:
            with ProcessPoolExecutor(
                max_workers=workers,
                initializer=_worker_init,
                initargs=(queue, log_level),
            ) as pool:
                futures = {pool.submit(run_simulation, c): c for c in configs}
                results = _collect(futures, log)
        finally:
            listener.stop()
            manager.shutdown()

    results.sort(key=lambda result: result.run_id)
    return results


def _collect(futures, log: logging.Logger) -> list[RunResult]:
    """Gather results as futures complete, keeping the batch alive on failure."""
    results: list[RunResult] = []
    for future in as_completed(futures):
        config = futures[future]
        try:
            results.append(future.result())
        except Exception as exc:  # noqa: BLE001 - worker died outright
            log.exception("run %d crashed: %s", config.run_id, exc)
            results.append(
                RunResult(
                    run_id=config.run_id,
                    seed=config.seed,
                    steps_completed=0,
                    wall_time_s=0.0,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return results


def log_summary(results: list[RunResult], elapsed: float, log: logging.Logger) -> None:
    """Log aggregate statistics for a finished batch."""
    ok = [result for result in results if result.ok]
    failed = [result for result in results if not result.ok]

    log.info("=" * 62)
    log.info("batch complete: %d ok, %d failed, %.2fs wall", len(ok), len(failed), elapsed)

    if ok:
        mr1 = [result.mr1_total for result in ok]
        mr2 = [result.mr2 for result in ok]
        burning = [result.burning_cells_final for result in ok]
        log.info("MR1 total   : mean=%.4f min=%.4f max=%.4f", _mean(mr1), min(mr1), max(mr1))
        log.info("MR2         : mean=%.2f min=%d max=%d", _mean(mr2), min(mr2), max(mr2))
        collisions = [result.collisions for result in ok]
        lost = [result.uavs_lost for result in ok]
        log.info("collisions  : mean=%.2f min=%d max=%d | UAVs lost: mean=%.2f max=%d",
                 _mean(collisions), min(collisions), max(collisions), _mean(lost), max(lost))
        # only reported when something in the batch actually ran with the fuel extension on
        dry = [result.uavs_out_of_fuel for result in ok]
        tanks = [value for result in ok for value in result.fuel_remaining]
        if any(dry) or tanks:
            log.info("out of fuel : mean=%.2f max=%d | tank left: mean=%.1f min=%.1f",
                     _mean(dry), max(dry), _mean(tanks), min(tanks, default=0.0))
        log.info("burning cells: mean=%.1f min=%d max=%d", _mean(burning), min(burning), max(burning))
        log.info("run time    : mean=%.2fs total=%.2fs",
                 _mean([result.wall_time_s for result in ok]),
                 sum(result.wall_time_s for result in ok))

        # win/lose only exists with the firefighting extension, since it is the home base that is lost
        scored = [result for result in ok if result.firefighting]
        if scored:
            lost_runs = [result for result in scored if result.lost]
            log.info("outcome     : %d WON, %d LOST of %d run(s) | lost proportion=%.1f%%",
                     len(scored) - len(lost_runs), len(lost_runs), len(scored),
                     100.0 * len(lost_runs) / len(scored))
            # only reported when out buildings were configured, NUM_OUT_BUILDINGS defaults to 0
            with_buildings = [result for result in scored if result.buildings_total]
            if with_buildings:
                destroyed = [result.buildings_lost for result in with_buildings]
                placed = max(result.buildings_total for result in with_buildings)
                log.info("out buildings destroyed: mean=%.2f min=%d max=%d of %d placed",
                         _mean(destroyed), min(destroyed), max(destroyed), placed)

    for result in failed:
        log.error("run %d failed: %s", result.run_id, result.error)
    log.info("=" * 62)


def _mean(values) -> float:
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_override(text: str) -> tuple[str, Any]:
    """Parse a NAME=VALUE override, evaluating VALUE as a Python literal."""
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"expected NAME=VALUE, got {text!r}")
    name, _, raw = text.partition("=")
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        value = raw  # fall back to the plain string, e.g. WIND_DIRECTION=south
    return name.strip(), value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the wildfire UAV simulation without visualization.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--runs", type=int, default=1, help="number of simulations to run (default: 1)")
    parser.add_argument(
        "--steps",
        type=int,
        default=None,
        help="steps per simulation (default: BATCH_SIZE from config.py)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="parallel workers; 0 uses one per CPU core (default: 1)",
    )
    parser.add_argument(
        "--executor",
        choices=("process", "thread"),
        default="process",
        help="parallelism backend. The simulation is CPU bound and holds the GIL, "
             "so 'process' is the only one that actually runs runs concurrently; "
             "'thread' is kept for debugging (default: process)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="base seed; run N uses seed+N so runs differ but the batch is reproducible",
    )
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        type=parse_override,
        default=[],
        metavar="NAME=VALUE",
        help="override a constant from config.py (repeatable)",
    )
    parser.add_argument(
        "--policy",
        default="random",
        help="policy that chooses UAV directions, see the policy/ package (default: random)",
    )
    parser.add_argument("--log-level", default="INFO",
                        choices=("DEBUG", "INFO", "WARNING", "ERROR"), help="console log level")
    parser.add_argument("--log-file", default=None, help="also write logs to this file")
    parser.add_argument("--log-every", type=int, default=10,
                        help="log simulation progress every N steps, 0 to disable (default: 10)")
    parser.add_argument("--output", default=None, help="write results as JSON to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    log = configure_logging(args.log_level, args.log_file)

    overrides = dict(args.overrides)
    cfg, _, _, policy_module = _import_simulation()
    steps = args.steps if args.steps is not None else overrides.get("BATCH_SIZE", cfg.BATCH_SIZE)

    # fail fast on an unknown policy name, rather than once per worker
    if args.policy not in policy_module.POLICIES:
        log.error("unknown policy %r, available: %s",
                  args.policy, ", ".join(sorted(policy_module.POLICIES)))
        return 2

    # likewise for the overrides: applying them here checks the whole configuration once, so a typo or an
    # out of bounds value is reported before the batch starts rather than as N identical failed runs.
    # Each worker applies them again in its own process, so this is a check and not the real application.
    try:
        apply_overrides(overrides)
    except (KeyError, ValueError) as exc:
        log.error("%s", exc)
        return 2

    workers = args.workers if args.workers > 0 else (os.cpu_count() or 1)
    workers = min(workers, args.runs)

    if args.seed is not None and args.executor == "thread" and workers > 1:
        log.warning(
            "seeding is process-global: with --executor thread the runs share one "
            "random state and results will not be reproducible"
        )

    configs = [
        RunConfig(
            run_id=run_id,
            steps=steps,
            seed=None if args.seed is None else args.seed + run_id,
            overrides=overrides,
            log_every=args.log_every,
            policy=args.policy,
        )
        for run_id in range(args.runs)
    ]

    started = time.perf_counter()
    results = run_batch(configs, workers, args.executor, args.log_level, log)
    elapsed = time.perf_counter() - started

    log_summary(results, elapsed, log)

    if args.output:
        # outcome is a property, so asdict() misses it; it is written out because it is what a
        # reader of the results wants, rather than having to combine 'firefighting' and 'lost'
        payload = [{**asdict(result), "outcome": result.outcome} for result in results]
        with open(args.output, "w") as handle:
            json.dump(payload, handle, indent=2)
        log.info("results written to %s", args.output)

    return 1 if any(not result.ok for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
