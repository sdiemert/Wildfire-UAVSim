#!/usr/bin/env python3
"""Runs simulations without the graphical interface.

The runner itself lives in sim/cli/. This file stays here so that the project can be run the way the README
describes it: `python3 headless.py --help` from the repository root.
"""

import sys

from sim.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
