"""How each agent is drawn on the grid.

The canvas asks for one portrayal per agent per cell per frame, so this is the hottest thing in the
interface. It is kept apart from app.py, which is only the server wiring, because this is the part anyone
changing the look of the map has to read.
"""

# own python modules

# imported as a module rather than with 'from config import ...', so that every setting is looked up when
# it is used. Naming the constants copies their values into this module's namespace, and a run that
# overrode one of them would go on being drawn with the value this file was imported with.
import config

from sim import agents, formulas


# the policy a UAV is flying right now, or None when nothing is allocating policies per UAV.
#
# Read through the model's policy by duck typing rather than by importing SuperPolicy: this module draws
# the managed system and has no business knowing which policy class is in charge, and a plain run -- where
# the model holds one ordinary Policy for the whole team -- simply has no allocated() to ask.
def allocated_policy(uav):
    allocated = getattr(getattr(uav.model, "policy", None), "allocated", None)
    if allocated is None:
        return None
    return allocated(uav.unique_id)[0]


# the colour to draw a UAV in. Near black unless COLOUR_UAVS_BY_POLICY is on and the policy it is flying
# has a colour of its own, in which case the map shows what the managing system decided.
def uav_color(uav):
    if not config.COLOUR_UAVS_BY_POLICY:
        return config.UAV_COLOR
    return config.POLICY_COLORS.get(allocated_policy(uav), config.UAV_COLOR)


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
                    idx = formulas.normalize_fuel_values(agent.get_fuel(), config.FUEL_UPPER_LIMIT)
                    portrayal.update({"Color": config.FIRE_COLORS[idx], "Layer": 0})
                elif config.ACTIVATE_FIREFIGHTING and agent.is_immune():  # showing a cell just hit by water
                    portrayal.update({"Color": config.EXTINGUISHED_COLOR, "Layer": 0})
                else:  # showing vegetation
                    idx = formulas.normalize_fuel_values(agent.get_fuel(), config.FUEL_UPPER_LIMIT)
                    portrayal.update({"Color": config.VEGETATION_COLORS[idx], "Layer": 0})
        elif type(agent) is agents.UAV:  # showing UAV, above the base so that it stays visible over it
            # a UAV is drawn dark whatever it is carrying, because that is what keeps it findable over the
            # light map; which dark colour says what policy it is flying, so that the managing system's
            # decision can be read off the map rather than off the panel beside it. The outline is what
            # gives it an edge over the base and over burnt ground, the only two things on the map
            # anywhere near as dark as it is.
            portrayal.update({"Color": uav_color(agent), "stroke_color": config.UAV_OUTLINE_COLOR,
                              "Layer": 2, "h": 0.85, "w": 0.85})
            # the water a UAV carries is shown by size rather than by colour: a UAV drawn full is
            # carrying its load, and a smaller one has dropped it and is on its way back to the base
            if config.ACTIVATE_FIREFIGHTING and not agent.has_water():
                portrayal.update({"h": 0.55, "w": 0.55})
    return portrayal
