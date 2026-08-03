"""Logging setup and the end of batch summary."""

from __future__ import annotations

# python libraries

import logging
import sys

LOGGER_NAME = "wildfire"
LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


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


def log_summary(results, elapsed: float, log: logging.Logger) -> None:
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
