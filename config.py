import random
import numpy

# COMMON VARIABLES

SYSTEM_RANDOM = random.SystemRandom()  # ... Not available on all systems ... (Python official doc)

# simulator activators (environment conditions)

FIXED_WIND = False
ACTIVATE_SMOKE = False
ACTIVATE_WIND = False
# To avoid throwing "KeyError: 'Layer'" when prob burning maps are shown (so UAV won't get its "Layer" attribute in the
# "portrayal_method(obj)"), NUM_AGENTS must be set to 0.
PROBABILITY_MAP = False

# model params specifications

BATCH_SIZE = 90
WIDTH = 50  # in python [height, width] for grid, in js [width, heigh]
HEIGHT = 50
BURNING_RATE = 1
FIRE_SPREAD_SPEED = 2
FUEL_UPPER_LIMIT = 10
FUEL_BOTTOM_LIMIT = 2

DENSITY_PROB = 1  # Tree density (Float number in the interval [0, 1])

WIND_DIRECTION = 'south'
# if FIXED_WIND == False (compose wind), then variables inside the if statement are set to be used in the project
if not FIXED_WIND:
    # Possible mixed wind directions: NW, NE, SW, SE"
    FIRST_DIR = 'south'  # Introduce first wind direction (north, south, east, west):
    SECOND_DIR = 'east'  # Introduce second wind direction (probability calculated based on first one),
    FIRST_DIR_PROB = 0.8  # Introduce first wind probability [0, 1]
MU = 0.9  # Wind velocity (Float number in the interval [0, 1])

SMOKE_PRE_DISPELLING_COUNTER = 2

# UAVs params

NUM_AGENTS = 1
N_ACTIONS = 4
# action indices, used to index the movement vectors in UAV.move()
ACTION_RIGHT = 0
ACTION_DOWN = 1
ACTION_LEFT = 2
ACTION_UP = 3
# "hold position" is deliberately outside N_ACTIONS, so that the random baseline keeps drawing from the
# original 4 movement actions. Policies that want it emit ACTION_STAY explicitly. Raise N_ACTIONS to 5 if
# you want a learning algorithm to treat holding position as part of the action space.
ACTION_STAY = 4
# dumping water is part of the firefighting extension below, and is likewise outside N_ACTIONS
ACTION_DUMP_WATER = 5
UAV_OBSERVATION_RADIUS = 4
side = ((UAV_OBSERVATION_RADIUS * 2) + 1)
N_OBSERVATIONS = side * side
SECURITY_DISTANCE = 10

# FIREFIGHTING EXTENSION
#
# Optional. When ACTIVATE_FIREFIGHTING is False every variable below is ignored and the simulation behaves
# exactly as it did before the extension existed. When it is True the simulation gains a home base, water
# carrying UAVs, extinguishing, re-ignition and out buildings.

ACTIVATE_FIREFIGHTING = True

# home base. UAVs start here and come back to refill.
# (x, y) cell, or None to place the base a quarter of the way into the grid. The default deliberately
# avoids the centre, because that is where set_fire_agents() lights the initial fire: a base on top of the
# ignition cell would be alight from step 1 and the UAVs would put the wildfire out before it ever spread.
BASE_POSITION = None
# footprint of the base, in cells, as (width, height). BASE_POSITION is its bottom left corner. The whole
# footprint is drawn blue, burns, and can be refilled from.
BASE_SIZE = (2, 2)
BHP = 5  # base health points: the run is lost once the base has burned for this many steps
BASE_REFILL_STEPS = 1  # steps a UAV must spend at the base to take on a load of water
BASE_CAPACITY = 1  # UAVs that can refill at the same time (the requirement is one)

# water carried by each UAV
UAV_WATER_CAPACITY = 1  # loads a UAV can carry at once

# water drops. A drop extinguishes the target cell and its surroundings, with a probability that falls off
# linearly with the distance from the centre of the drop.
WATER_DROP_RADIUS = 2  # cells around the drop position that are affected
WATER_EXTINGUISH_PROB_CENTRE = 0.95  # probability of extinguishing the cell the water is dumped on
WATER_EXTINGUISH_PROB_EDGE = 0.60  # probability of extinguishing a cell at WATER_DROP_RADIUS

# re-ignition of extinguished cells
REIGNITION_DELAY = 8  # steps an extinguished cell is immune; afterwards nearby fire can light it again
SPONTANEOUS_REIGNITION_PROB = 0.005  # per step chance an extinguished cell relights on its own

# out buildings scattered over the map, which burn and are worth protecting
NUM_OUT_BUILDINGS = 0
OUT_BUILDING_HP = 5  # steps an out building survives while its cell burns

# colors

BASE_COLOR = "#1f6fff"  # blue, as the home base is shown on the map
BASE_BURNING_COLOR = "#7c3aed"
OUT_BUILDING_COLOR = "#8b5a2b"
OUT_BUILDING_DESTROYED_COLOR = "#3b3b3b"
EXTINGUISHED_COLOR = "#5fd0e8"  # cells that were recently hit by water

VEGETATION_COLORS = ["#414141", "#9eff89", "#85e370", "#72d05c", "#62c14c", "#459f30",
                     "#389023", "#2f831b", "#236f11", "#1c630b", "#175808", "#124b05"]
FIRE_COLORS = ["#414141", "#d8d675", "#eae740", "#fefa01", "#fed401", "#feaa01",
               "#fe7001", "#fe5501", "#fe3e01", "#fe2f01", "#fe2301", "#fe0101"]
SMOKE_COLORS = ["#ababab"]
BLACK_AND_WHITE_COLORS = ["#ffffff", "#e6e6e6", "#c9c9c9", "#b1b1b1", "#a1a1a1", "#818181",
                          "#636363", "#474747", "#303030", "#1a1a1a", "#000000"]
COLORS_LEN = len(VEGETATION_COLORS)


# functions

# function that normalize fuel values to fit them with vegetation and fire colors
def normalize_fuel_values(fuel, limit):
    if fuel > limit:
        fuel = limit
    return max(0, round((fuel / limit) * COLORS_LEN - 1))


# function that normalize any number into a desired range
def normalize(to_normalize, upper, multiplier, subtractor):
    return ((to_normalize / upper) * multiplier) - subtractor


# function that calculates the Euclidean distance between two certain positions
def euclidean_distance(x1, y1, x2, y2):
    a = numpy.array((x1, y1))
    b = numpy.array((x2, y2))
    dist = numpy.linalg.norm(a - b)
    return dist


# function that gives the probability of a water drop centred on drop_pos extinguishing the cell at
# cell_pos. It is WATER_EXTINGUISH_PROB_CENTRE right under the drop, falls off linearly with the distance,
# reaches WATER_EXTINGUISH_PROB_EDGE at WATER_DROP_RADIUS, and is zero beyond it.
def extinguish_probability(drop_pos, cell_pos):
    distance = euclidean_distance(drop_pos[0], drop_pos[1], cell_pos[0], cell_pos[1])
    if distance > WATER_DROP_RADIUS:
        return 0.0
    if WATER_DROP_RADIUS == 0:
        return WATER_EXTINGUISH_PROB_CENTRE
    ratio = distance / WATER_DROP_RADIUS
    return WATER_EXTINGUISH_PROB_CENTRE + ratio * (WATER_EXTINGUISH_PROB_EDGE - WATER_EXTINGUISH_PROB_CENTRE)


# function that calculates the grade of influence of cell s' over cell s, based on a distance_limit
def distance_rate(s, s_, distance_limit):
    m_d = euclidean_distance(s[0], s[1], s_[0], s_[1])
    result = 0
    if m_d <= distance_limit:
        result = m_d ** -2.0
    return result
