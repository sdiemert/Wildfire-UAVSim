"""The headless command line runner.

  main.py       the argument parser and the entry point
  runner.py     one simulation start to finish: RunConfig in, RunResult out
  batch.py      several of them, in parallel when asked
  overrides.py  --set and --seed, both of which work by setting attributes on config
  reporting.py  logging setup and the end of batch summary

Run it as `python3 headless.py` from the repository root, or as `python3 -m sim.cli.main`.
"""

from sim.cli.batch import run_batch
from sim.cli.main import main
from sim.cli.runner import RunConfig, RunResult, run_simulation

__all__ = ["RunConfig", "RunResult", "main", "run_batch", "run_simulation"]
