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

from sim.adaptive import AdaptiveWildFireModel
from sim.gui.canvas_grid import CanvasGrid
from sim.gui.policy_selector import ControlGate, PolicySelector
from sim.gui.portrayal import agent_portrayal
from sim.gui.status_sidebar import StatusSidebar
from sim.gui.top_bar import TopBar
from sim.policy import POLICIES, RandomPolicy


# builds the settings of the web page. Mesa passes the current value of each one to the model as a keyword
# argument, both on start up and every time Reset is pressed. Mesa renders them into the left hand sidebar;
# PolicySelector then carries each control over to the strip above the grid, in the order listed here.
#
# The managing system control is here rather than only in config.py because the whole point of it is to be
# able to compare the three arrangements -- unmanaged, managed here, managed on a server -- without editing
# a file and restarting the server. AdaptiveWildFireModel takes both of these as per model overrides and
# never writes them back to config, so a Reset with different settings builds a different model rather than
# changing the configuration for everything built afterwards.
#
# The UAV policy control is gated on it by ControlGate in main(), below: it is only the run's policy while
# nothing is managing the fleet.
def model_params():
    return {
        "managing": mesa.visualization.Choice(
            name="Managing system",
            value=config.MANAGING_SYSTEM,
            choices=list(config.MANAGING_SYSTEMS),
            description="Whether a MAPE-K managing system runs over the simulation, reallocating a "
                        "policy to each UAV as the run goes, and where it lives. 'none' is the "
                        "unmanaged baseline: every UAV flies the policy below for the whole run. "
                        "'local' runs the whole loop in this process. 'remote' runs it on the server "
                        "at MANAGING_SYSTEM_URL, which analyses, plans and remembers over there; only "
                        "the sensor and the effector stay here. Overrides MANAGING_SYSTEM in config.py "
                        "for this run only. Press Reset to apply.",
        ),
        "policy": mesa.visualization.Choice(
            name="UAV policy",
            value=config.DEFAULT_UAV_POLICY if config.MANAGING_SYSTEM != "none" else RandomPolicy.name,
            choices=sorted(POLICIES),
            description="Rule that decides which direction each UAV flies, for the whole run. Only "
                        "available with the managing system set to 'none': a managing system allocates "
                        "a policy to each UAV itself, and would overwrite this within a few steps. "
                        "Press Reset to apply.",
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
    # the starting value of the dropdown; it can be changed on the page without restarting the server
    print('managing system:', config.MANAGING_SYSTEM)

    # initialize CanvasGrid
    grid = CanvasGrid(agent_portrayal, config.WIDTH, config.HEIGHT, 10 * config.WIDTH, 10 * config.HEIGHT)
    # live status panel, rendered in the sidebar next to the grid
    sidebar = StatusSidebar()
    # gathers the speed slider, the step counter and the run buttons into the bar along the top
    topbar = TopBar()
    # moves the model parameter dropdowns over to the right hand side, above the grid: one selector per
    # control, stacked in the order model_params() lists them, so there is one place to change the order
    # and nothing here to keep in step with it
    selectors = [PolicySelector(name) for name in model_params()]
    # the UAV policy is only the run's policy while nothing is managing the fleet; with a managing system
    # running it allocates one per UAV and would overwrite the choice within a few steps, so the control
    # is greyed out and held at the policy the team will actually start under
    selectors.append(ControlGate(
        param="policy", depends_on="managing", enabled_for=["none"],
        disabled_value=config.DEFAULT_UAV_POLICY,
        reason="The managing system allocates a policy to each UAV. "
               "Set 'Managing system' to 'none' to choose one yourself.",
    ))
    # initialize Modular server for mesa Python visualization. AdaptiveWildFireModel is served whatever
    # the managing system dropdown says: with it off the model builds no sensor and no effector and is
    # the plain WildFireModel, so there is nothing to choose between here.
    server = mesa.visualization.ModularServer(AdaptiveWildFireModel,
                                              [grid, sidebar, topbar, *selectors],
                                              "WildFire Model", model_params())
    server.port = 8521  # default port, others can be set
    server.launch()


# guarded, so that importing this module (to reuse agent_portrayal, or simply to check that it parses)
# does not launch a web server on port 8521
if __name__ == "__main__":
    main()
