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

    # the experiment the managing system exists for: the same fires, with and without it
    python3 headless.py --runs 30 --workers 4 --seed 1 --managing none      --output baseline.json
    python3 headless.py --runs 30 --workers 4 --seed 1 --managing heuristic --output adaptive.json

    # every managing system there is, and one arm of the experiment per line
    python3 headless.py --list-managing

    # a combination nobody has registered: the default system with one component swapped
    python3 headless.py --managing heuristic --mape planner=defensive --mape analyzer=cautious

    # run the managing system on a server instead of in this process
    python3 headless.py --managing remote --managing-url http://127.0.0.1:8600/manage
"""

from __future__ import annotations

# python libraries

import argparse
import json
import os
import sys
import time
from dataclasses import asdict

# own python modules

from sim.cli.batch import run_batch
from sim.cli.overrides import _import_simulation, apply_overrides, parse_override
from sim.cli.reporting import configure_logging, log_summary
from sim.cli.runner import RunConfig


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
        help="policy that chooses UAV directions, see the sim/policy/ package (default: random). "
             "With the managing system on this is only what the team starts under, before the first "
             "adaptation",
    )
    parser.add_argument(
        "--managing",
        default=None,
        metavar="NAME",
        help="which MAPE-K managing system runs over the simulation, reallocating a policy to each UAV as "
             "the run goes; 'none' is the unmanaged baseline. See --list-managing for the ones there are, "
             "and sim/managing/systems.py to add another (default: MANAGING_SYSTEM from config.py)",
    )
    parser.add_argument(
        "--mape",
        dest="components",
        action="append",
        type=parse_override,
        default=[],
        metavar="ROLE=NAME",
        help="override one MAPE-K component of the selected managing system, e.g. --mape planner=static "
             "(repeatable). ROLE is one of monitor, analyzer, planner, executor, knowledge. This is for a "
             "combination worth trying but not worth naming; a combination worth naming goes in "
             "sim/managing/systems.py",
    )
    parser.add_argument(
        "--managing-url",
        default=None,
        help="where a remote managing system lives, see sim/managing/remote.py for the contract "
             "(default: MANAGING_SYSTEM_URL from config.py)",
    )
    parser.add_argument(
        "--list-managing",
        action="store_true",
        help="print the managing systems that can be selected with --managing, and what each is made of",
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

    # the managing systems are read from the registry rather than listed here, so this stays right as they
    # are added. It is answered before anything else, because it is a question about the code and not a run.
    if args.list_managing:
        from sim.managing.systems import REGISTERED

        for spec in REGISTERED:
            print(f"  {spec.describe()}")
            print(f"      {spec.description}")
        return 0

    overrides = dict(args.overrides)
    components = dict(args.components)

    # the managing system options are folded into the overrides rather than carried separately, because
    # every one of them is already a setting in config.py and the overrides are how a run changes those.
    # They are applied after --set, so an explicit flag wins over a --set of the same constant.
    if args.managing is not None:
        overrides["MANAGING_SYSTEM"] = args.managing
    if args.managing_url is not None:
        overrides["MANAGING_SYSTEM_URL"] = args.managing_url

    cfg, _, _, policy_module = _import_simulation()
    steps = args.steps if args.steps is not None else overrides.get("BATCH_SIZE", cfg.BATCH_SIZE)

    # fail fast on an unknown policy name, rather than once per worker
    if args.policy not in policy_module.POLICIES:
        log.error("unknown policy %r, available: %s",
                  args.policy, ", ".join(sorted(policy_module.POLICIES)))
        return 2

    # likewise for the managing system and any component overrides: resolving them here reports a mistyped
    # name once, before the batch starts, rather than as N identical failed runs
    from sim.managing.systems import managing_system

    try:
        managing_system(overrides.get("MANAGING_SYSTEM", cfg.MANAGING_SYSTEM)).with_components(components)
    except KeyError as exc:
        log.error("%s", exc.args[0] if exc.args else exc)
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
            managing_components=components,
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
