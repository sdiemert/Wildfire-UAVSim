# python libraries

import logging

import mesa

from Canvas_Grid_Visualization import CanvasGrid
from Policy_Selector import PolicySelector
from Status_Sidebar import StatusSidebar
from Top_Bar import TopBar

# own python modules

import wildfire_model
import agents

from sim.policy import POLICIES, RandomPolicy

# imported as a module rather than with 'from config import *', so that every setting is looked up when it
# is used. A star import copies the values into this module's namespace, which is why a runner overriding a
# constant (see headless.py) used to have to reach into every module that had copied it. Reading through
# 'config' leaves one copy to patch, the way the policy package has always done it.
import config


# creates agent dictionary for rendering it on Canvas Gird from Mesa framework
def agent_portrayal(agent):
    portrayal = {"Shape": "rect", "Filled": True, "h": 1, "w": 1}
    # showing the probability map
    if config.PROBABILITY_MAP:
        if type(agent) is agents.Fire:
            idx = int(round(agent.get_prob(), 1) * 10)
            portrayal.update({"Color": config.BLACK_AND_WHITE_COLORS[idx], "Layer": 0})
        else:
            # nothing else is drawn on the probability map, and returning a portrayal without a "Layer"
            # would throw a KeyError in the canvas
            return None
    else:
        if type(agent) is agents.Base or type(agent) is agents.BaseTile:
            # showing the home base, drawn above the vegetation. Every cell of its footprint is drawn, so
            # the base appears as a solid BASE_SIZE block.
            base = agent if type(agent) is agents.Base else agent.base
            color = config.BASE_BURNING_COLOR if base.is_burning() else config.BASE_COLOR
            portrayal.update({"Color": color, "Layer": 1})
        elif type(agent) is agents.OutBuilding:  # showing an out building
            color = config.OUT_BUILDING_DESTROYED_COLOR if agent.destroyed else config.OUT_BUILDING_COLOR
            portrayal.update({"Color": color, "Layer": 1, "h": 0.7, "w": 0.7})
        elif type(agent) is agents.Fire:  # showing smoke
            if agent.smoke.is_smoke_active():
                # the two following lines of code could be used to set the normalized index for different smoke colors.
                # only one color is used by default.
                # idx = normalize_fuel_values(agent.smoke.get_dispelling_counter_value(),
                # agent.smoke.get_dispelling_counter_start_value())
                portrayal.update({"Color": config.SMOKE_COLORS[0], "Layer": 0})
            else:
                if agent.is_burning():  # showing fire
                    idx = config.normalize_fuel_values(agent.get_fuel(), config.FUEL_UPPER_LIMIT)
                    portrayal.update({"Color": config.FIRE_COLORS[idx], "Layer": 0})
                elif config.ACTIVATE_FIREFIGHTING and agent.is_immune():  # showing a cell just hit by water
                    portrayal.update({"Color": config.EXTINGUISHED_COLOR, "Layer": 0})
                else:  # showing vegetation
                    idx = config.normalize_fuel_values(agent.get_fuel(), config.FUEL_UPPER_LIMIT)
                    portrayal.update({"Color": config.VEGETATION_COLORS[idx], "Layer": 0})
        elif type(agent) is agents.UAV:  # showing UAV, above the base so that it stays visible over it
            # every UAV is drawn in the same near black, whatever it is carrying, because that is what
            # keeps it findable over the light map. The outline is what gives it an edge over the base
            # and over burnt ground, the only two things on the map anywhere near as dark as it is.
            portrayal.update({"Color": config.UAV_COLOR, "stroke_color": config.UAV_OUTLINE_COLOR,
                              "Layer": 2, "h": 0.85, "w": 0.85})
            # the water a UAV carries is shown by size rather than by colour: a UAV drawn full is
            # carrying its load, and a smaller one has dropped it and is on its way back to the base
            if config.ACTIVATE_FIREFIGHTING and not agent.has_water():
                portrayal.update({"h": 0.55, "w": 0.55})
    return portrayal


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
