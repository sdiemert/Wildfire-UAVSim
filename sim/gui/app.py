"""The Mesa web interface.

Wires the four visualization elements onto a ModularServer and launches it. Run it with

    python3 main.py

from the repository root, or as `python3 -m sim.gui.app`.
"""

# python libraries

import logging

import mesa

# own python modules

import config

from sim import model as wildfire_model
from sim.gui.canvas_grid import CanvasGrid
from sim.gui.policy_selector import PolicySelector
from sim.gui.portrayal import agent_portrayal
from sim.gui.status_sidebar import StatusSidebar
from sim.gui.top_bar import TopBar
from sim.policy import POLICIES, RandomPolicy


# builds the settings of the web page. Mesa passes the current value of each one to WildFireModel as a
# keyword argument, both on start up and every time Reset is pressed. Mesa renders them into the left hand
# sidebar; PolicySelector then carries the policy control over to the strip above the grid.
def model_params():
    policy_names = sorted(POLICIES)
    return {
        "policy": mesa.visualization.Choice(
            name="UAV policy",
            value=RandomPolicy.name,
            choices=policy_names,
            description="Rule that decides which direction each UAV flies. "
                        "Pick one and press Reset to restart the simulation with it.",
        ),
    }


# function that holds the main logic, in which the wildfire simulation and the web page interface are launched
def main():
    # the model and its agents report through the "wildfire" logger, so give it somewhere to write
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
                        datefmt="%H:%M:%S")

    print('actions:', config.N_ACTIONS)
    print('observations:', config.N_OBSERVATIONS)
    print('policies:', ', '.join(sorted(POLICIES)))

    # initialize CanvasGrid
    grid = CanvasGrid(agent_portrayal, config.WIDTH, config.HEIGHT, 10 * config.WIDTH, 10 * config.HEIGHT)
    # live status panel, rendered in the sidebar next to the grid
    sidebar = StatusSidebar()
    # gathers the speed slider, the step counter and the run buttons into the bar along the top
    topbar = TopBar()
    # moves the UAV policy dropdown over to the right hand side, above the grid
    policy = PolicySelector("policy")
    # initialize Modular server for mesa Python visualization
    server = mesa.visualization.ModularServer(wildfire_model.WildFireModel, [grid, sidebar, topbar, policy],
                                              "WildFire Model", model_params())
    server.port = 8521  # default port, others can be set
    server.launch()


# guarded, so that importing this module (to reuse agent_portrayal, or simply to check that it parses)
# does not launch a web server on port 8521
if __name__ == "__main__":
    main()
