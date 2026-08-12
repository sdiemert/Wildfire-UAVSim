#!/usr/bin/env python3
"""Records the configuration the parameter space sweep actually ran under.

design.py names the eight parameters that vary and the sixteen constants every arm holds; the runs depend
on every other setting in config.py as well, and those are only the defaults *as of the recorded commit*.
This applies the constants through the same code path headless.py uses and writes the whole resulting
configuration to config-used.json, together with the design and the commit, which is what a later reader
should diff against.

The swept parameters are left at their config.py defaults in the record: an arm overrides all eight, so
the value written here for BHP or DENSITY_PROB is not what any arm ran with. The 'design' block is where
their ranges are.

Run from the repository root:  python3 experiments/20260811_paramspace/dump_config.py
"""

# python libraries

import json
import pathlib
import subprocess
import sys

# own python modules

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sim.cli.overrides import apply_overrides

import design as design_module  # noqa: E402 - after the sys.path insert above

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]


# whether a config attribute is a setting rather than machinery. SYSTEM_RANDOM, validate() and the
# imported modules are all attributes of the module too, and none of them belongs in the record.
def is_setting(name, value):
    return (name.isupper()
            and not name.startswith("_")
            and isinstance(value, (int, float, str, bool, tuple, list, type(None))))


def main():
    import config

    apply_overrides(dict(design_module.CONSTANTS))

    settings = {name: getattr(config, name) for name in sorted(dir(config))
                if is_setting(name, getattr(config, name))}

    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()

    record = {
        "commit": commit,
        "constants": {name: list(value) if isinstance(value, tuple) else value
                      for name, value in design_module.CONSTANTS.items()},
        "design": {
            "design_seed": design_module.DESIGN_SEED,
            "seed_base": design_module.SEED_BASE,
            "n_arms": design_module.N_ARMS,
            "runs_per_arm": design_module.RUNS_PER_ARM,
            "dimensions": list(design_module.DIMENSIONS),
            "ranges": {name: list(value) for name, value in design_module.RANGES.items()},
            "fuel_upper_ceiling": design_module.FUEL_UPPER_CEILING,
            "compass": list(design_module.COMPASS),
        },
        # the swept eight are in here at their config.py defaults, not at any value an arm ran with
        "config": {name: list(value) if isinstance(value, tuple) else value
                   for name, value in settings.items()},
    }

    with open(HERE / "config-used.json", "w") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")

    print(f"commit {commit}")
    print(f"{len(settings)} settings written to {HERE / 'config-used.json'}")
    print(f"{design_module.N_ARMS} arms x {design_module.RUNS_PER_ARM} runs "
          f"= {design_module.N_ARMS * design_module.RUNS_PER_ARM} runs")


if __name__ == "__main__":
    main()
