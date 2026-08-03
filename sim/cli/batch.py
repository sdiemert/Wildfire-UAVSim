"""Running several independent simulations, in parallel when asked.

The simulation is CPU bound and holds the GIL, so 'process' is the only backend that actually runs runs
concurrently. Worker processes ship their log records back to the parent over a queue, which is what keeps
the output of a parallel batch readable.
"""

from __future__ import annotations

# python libraries

import logging
import logging.handlers
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import Any

# own python modules

from sim.cli.reporting import LOGGER_NAME
from sim.cli.runner import RunConfig, RunResult, run_simulation

# queue used by worker processes to ship log records back to the parent
_LOG_QUEUE: Any = None


def _worker_init(queue, level: str) -> None:
    """Initializer for pool workers: send all log records to the parent."""
    global _LOG_QUEUE
    _LOG_QUEUE = queue

    log = logging.getLogger(LOGGER_NAME)
    log.setLevel(getattr(logging, level.upper()))
    log.propagate = False
    log.handlers.clear()
    log.addHandler(logging.handlers.QueueHandler(queue))


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
