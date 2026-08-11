#!/usr/bin/env python3
"""Records the configuration the wind sweeps actually ran under.

run.sh names the settings every arm holds fixed and the axes that vary; the runs depend on every other
setting in config.py as well, and those are only the defaults *as of the recorded commit*. This applies the
base overrides through the same code path headless.py uses and writes the whole resulting configuration to
config-used.json, together with the axes and the commit, which is what a later reader should diff against.

The base here is deliberately the twelve settings of experiments/20260810_baseline/ with the wind switched
on: the point of the experiment is that the wind is the only thing that changed.

Run from the repository root:  python3 experiments/20260810_wind/dump_config.py
"""

# python libraries

import json
import pathlib
import subprocess
import sys

# own python modules

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sim.cli.overrides import apply_overrides

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# held fixed in every arm of every sweep -- the baseline's twelve, with ACTIVATE_WIND flipped on
BASE = {
    "WIDTH": 100,
    "HEIGHT": 100,
    "BATCH_SIZE": 100,
    "NUM_AGENTS": 0,
    "ACTIVATE_FIREFIGHTING": True,
    "BHP": 4,
    "FIRE_START_POSITION": "random",
    "FIRE_START_STEP": 0,
    "BURNING_RATE": 1,
    "FIRE_SPREAD_SPEED": 1,
    "DENSITY_PROB": 1.0,
    "ACTIVATE_SMOKE": False,
    "ACTIVATE_WIND": True,
}

# what each sweep varied on top of that, and the seed block it drew its fires from
SWEEPS = {
    "cardinal": {
        "fixed": {"FIXED_WIND": True},
        "axes": {"WIND_DIRECTION": ["north", "south", "east", "west"],
                 "MU": [0.0, 0.25, 0.5, 0.75, 0.85, 0.9, 0.95, 0.975, 0.99, 1.0]},
        "runs_per_arm": 1000,
        "seed": 3000000,
    },
    "diagonal": {
        "fixed": {"FIXED_WIND": False, "FIRST_DIR_PROB": 0.5},
        "axes": {"FIRST_DIR": ["north", "south"], "SECOND_DIR": ["east", "west"],
                 "MU": [0.0, 0.75, 0.85, 0.9, 0.95, 0.975, 0.99, 1.0]},
        "runs_per_arm": 250,
        "seed": 3000000,
    },
    "runlength": {
        "fixed": {"FIXED_WIND": True, "WIND_DIRECTION": "south"},
        "axes": {"BATCH_SIZE": [50, 100, 200, 400],
                 "MU": [0.5, 0.75, 0.85, 0.9, 0.95, 0.975, 0.99, 1.0]},
        "runs_per_arm": 500,
        "seed": 4000000,
    },
    "steadiness": {
        "fixed": {"FIXED_WIND": False, "FIRST_DIR": "south", "SECOND_DIR": "east"},
        "axes": {"FIRST_DIR_PROB": [0.5, 0.6, 0.7, 0.8, 0.9, 1.0], "MU": [0.95, 1.0]},
        "runs_per_arm": 250,
        "seed": 5000000,
    },
    # the odd one out: no home base, so no loss rate. Read by extent.py, not analyse.py.
    "extent": {
        "fixed": {"FIXED_WIND": True, "WIND_DIRECTION": "south", "ACTIVATE_FIREFIGHTING": False},
        "axes": {"MU": [0.0, 0.25, 0.5, 0.75, 0.85, 0.9, 0.95, 0.975, 0.99, 1.0]},
        "runs_per_arm": 200,
        "seed": 6000000,
    },
}


# whether a config attribute is a setting rather than machinery. SYSTEM_RANDOM, validate() and the
# imported modules are all attributes of the module too, and none of them belongs in the record.
def is_setting(name, value):
    return (name.isupper()
            and not name.startswith("_")
            and isinstance(value, (int, float, str, bool, tuple, list, type(None))))


def main():
    import config

    apply_overrides(BASE)

    settings = {name: getattr(config, name) for name in sorted(dir(config))
                if is_setting(name, getattr(config, name))}

    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()

    record = {
        "commit": commit,
        "base": BASE,
        "sweeps": SWEEPS,
        "config": {name: list(value) if isinstance(value, tuple) else value
                   for name, value in settings.items()},
    }

    with open(HERE / "config-used.json", "w") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")

    arms = sum(_product(sweep["axes"]) for sweep in SWEEPS.values())
    runs = sum(_product(sweep["axes"]) * sweep["runs_per_arm"] for sweep in SWEEPS.values())
    print(f"commit {commit}")
    print(f"{len(settings)} settings written to {HERE / 'config-used.json'}")
    print(f"{arms} arms, {runs} runs")


def _product(axes):
    total = 1
    for values in axes.values():
        total *= len(values)
    return total


if __name__ == "__main__":
    main()
