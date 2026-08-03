#!/usr/bin/env python3
"""Launches the web interface.

The interface itself lives in sim/gui/. This file stays here so that the project can be run the way the
README describes it: open main.py in PyCharm and press Run, or `python3 main.py` from the repository root.
"""

from sim.gui.app import main

if __name__ == "__main__":
    main()
