"""Overriding simulation constants for a run, and seeding it.

Both work by setting attributes on the config module, which reaches the whole simulation because every
module reads its settings through `config.` at the point of use rather than copying the values in.
"""

from __future__ import annotations

# python libraries

import argparse
import ast
import random
from typing import Any


def _import_simulation():
    """Import the simulation modules.

    Returned as a tuple so that apply_overrides() and seed_simulation() can walk
    them. The simulation itself is headless: nothing in it imports matplotlib,
    so there is no GUI backend to force here.
    """
    import config as cfg
    from sim import agents, policy
    from sim import model as wildfire_model

    return cfg, wildfire_model, agents, policy


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
