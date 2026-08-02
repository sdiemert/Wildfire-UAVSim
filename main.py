# python libraries

import logging

import mesa

from Canvas_Grid_Visualization import CanvasGrid
from Fps_Topbar import FpsTopbar
from Status_Sidebar import StatusSidebar

# own python modules

import wildfire_model
import agents

from policy import POLICIES, RandomPolicy

from config import *


# creates agent dictionary for rendering it on Canvas Gird from Mesa framework
def agent_portrayal(agent):
    portrayal = {"Shape": "rect", "Filled": True, "h": 1, "w": 1}
    # showing the probability map
    if PROBABILITY_MAP:
        if type(agent) is agents.Fire:
            idx = int(round(agent.get_prob(), 1) * 10)
            portrayal.update({"Color": BLACK_AND_WHITE_COLORS[idx], "Layer": 0})
        else:
            # nothing else is drawn on the probability map, and returning a portrayal without a "Layer"
            # would throw a KeyError in the canvas
            return None
    else:
        if type(agent) is agents.Base or type(agent) is agents.BaseTile:
            # showing the home base, drawn above the vegetation. Every cell of its footprint is drawn, so
            # the base appears as a solid BASE_SIZE block.
            base = agent if type(agent) is agents.Base else agent.base
            color = BASE_BURNING_COLOR if base.is_burning() else BASE_COLOR
            portrayal.update({"Color": color, "Layer": 1})
        elif type(agent) is agents.OutBuilding:  # showing an out building
            color = OUT_BUILDING_DESTROYED_COLOR if agent.destroyed else OUT_BUILDING_COLOR
            portrayal.update({"Color": color, "Layer": 1, "h": 0.7, "w": 0.7})
        elif type(agent) is agents.Fire:  # showing smoke
            if agent.smoke.is_smoke_active():
                # the two following lines of code could be used to set the normalized index for different smoke colors.
                # only one color is used by default.
                # idx = normalize_fuel_values(agent.smoke.get_dispelling_counter_value(),
                # agent.smoke.get_dispelling_counter_start_value())
                portrayal.update({"Color": SMOKE_COLORS[0], "Layer": 0})
            else:
                if agent.is_burning():  # showing fire
                    idx = normalize_fuel_values(agent.get_fuel(), FUEL_UPPER_LIMIT)
                    portrayal.update({"Color": FIRE_COLORS[idx], "Layer": 0})
                elif ACTIVATE_FIREFIGHTING and agent.is_immune():  # showing a cell just hit by water
                    portrayal.update({"Color": EXTINGUISHED_COLOR, "Layer": 0})
                else:  # showing vegetation
                    idx = normalize_fuel_values(agent.get_fuel(), FUEL_UPPER_LIMIT)
                    portrayal.update({"Color": VEGETATION_COLORS[idx], "Layer": 0})
        elif type(agent) is agents.UAV:  # showing UAV, above the base so that it stays visible over it
            # a UAV still carrying water is drawn hollow, so that its load is visible on the map
            portrayal.update({"Color": "Black", "Layer": 2, "h": 0.8, "w": 0.8})
            if ACTIVATE_FIREFIGHTING and agent.has_water():
                portrayal.update({"Color": "#00306b", "h": 0.5, "w": 0.5})
    return portrayal


# builds the settings shown on the left hand side of the web page. Mesa passes the current value of each
# one to WildFireModel as a keyword argument, both on start up and every time Reset is pressed.
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

    print('actions:', N_ACTIONS)
    print('observations:', N_OBSERVATIONS)
    print('policies:', ', '.join(sorted(POLICIES)))

    # initialize CanvasGrid
    grid = CanvasGrid(agent_portrayal, WIDTH, HEIGHT, 10 * WIDTH, 10 * HEIGHT)
    # live status panel, rendered in the sidebar next to the grid
    sidebar = StatusSidebar()
    # moves the frames per second slider up into the top bar, beside the run controls
    fps = FpsTopbar()
    # initialize Modular server for mesa Python visualization
    server = mesa.visualization.ModularServer(wildfire_model.WildFireModel, [grid, sidebar, fps],
                                              "WildFire Model", model_params())
    server.port = 8521  # default port, others can be set
    server.launch()


main()
