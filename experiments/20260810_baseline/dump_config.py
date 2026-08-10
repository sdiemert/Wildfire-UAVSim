#!/usr/bin/env python3
"""Records the configuration the baseline arm actually ran under.

The command in README.md names twelve overrides; the run depends on every other setting in config.py as
well, and those are only the defaults *as of the recorded commit*. Rather than trust that they never
move, this applies the same overrides through the same code path headless.py uses and writes the whole
resulting configuration to config-used.json, which is what a later reader should diff against.

Run from the repository root:  python3 experiments/20260810_baseline/dump_config.py
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

# the twelve --set overrides from the run command in README.md, in the same order
OVERRIDES = {
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
    "ACTIVATE_WIND": False,
    "ACTIVATE_SMOKE": False,
}


# whether a config attribute is a setting rather than machinery. SYSTEM_RANDOM, validate() and the
# imported modules are all attributes of the module too, and none of them belongs in the record.
def is_setting(name, value):
    return (name.isupper()
            and not name.startswith("_")
            and isinstance(value, (int, float, str, bool, tuple, list, type(None))))


def main():
    import config

    apply_overrides(OVERRIDES)

    settings = {name: getattr(config, name) for name in sorted(dir(config))
                if is_setting(name, getattr(config, name))}

    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()

    record = {
        "commit": commit,
        "overrides": OVERRIDES,
        "config": {name: list(value) if isinstance(value, tuple) else value
                   for name, value in settings.items()},
    }

    with open(HERE / "config-used.json", "w") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")

    print(f"commit {commit}")
    print(f"{len(settings)} settings written to {HERE / 'config-used.json'}")


if __name__ == "__main__":
    main()
