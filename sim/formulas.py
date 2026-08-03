"""Shared maths.

Kept in one place so that the model, the agents, the policies and the interface all use the same
definitions: a policy that estimates how far its remaining fuel will take it has to work it out exactly the
way the model charges for it, or the two drift apart.

These used to live at the bottom of config.py. They read their settings through `config.` rather than
importing the constants by name, which is what lets a runner or a test override one of them and have these
functions pick it up. config.py itself must never import this module: it is imported here, so an import in
the other direction would be a cycle.
"""

# python libraries

import math

# own python modules

import config


# function that normalize fuel values to fit them with vegetation and fire colors
def normalize_fuel_values(fuel, limit):
    if fuel > limit:
        fuel = limit
    return max(0, round((fuel / limit) * config.COLORS_LEN - 1))


# function that normalize any number into a desired range
def normalize(to_normalize, upper, multiplier, subtractor):
    return ((to_normalize / upper) * multiplier) - subtractor


# function that calculates the Euclidean distance between two certain positions. math.hypot rather than
# numpy: this is called on two scalars, once per pair of UAVs per step by MR2() and once per cell of a
# water drop, and building two one dimensional arrays to take a norm of them costs far more than the
# arithmetic does.
def euclidean_distance(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)


# function that gives the probability of a water drop centred on drop_pos extinguishing the cell at
# cell_pos. It is WATER_EXTINGUISH_PROB_CENTRE right under the drop, falls off linearly with the distance,
# reaches WATER_EXTINGUISH_PROB_EDGE at WATER_DROP_RADIUS, and is zero beyond it.
def extinguish_probability(drop_pos, cell_pos):
    distance = euclidean_distance(drop_pos[0], drop_pos[1], cell_pos[0], cell_pos[1])
    if distance > config.WATER_DROP_RADIUS:
        return 0.0
    if config.WATER_DROP_RADIUS == 0:
        return config.WATER_EXTINGUISH_PROB_CENTRE
    ratio = distance / config.WATER_DROP_RADIUS
    return config.WATER_EXTINGUISH_PROB_CENTRE + ratio * (config.WATER_EXTINGUISH_PROB_EDGE -
                                                          config.WATER_EXTINGUISH_PROB_CENTRE)


# function that rolls the health points one collision takes off one UAV. The result is a whole health
# point with probability UAV_COLLISION_DAMAGE_MEAN and nothing at all otherwise, so the damage is bounded
# to a single point however the mean is set, and averages out at the mean over many collisions. A mean of
# 1.0 always costs the point, because random() never reaches 1, and a mean of 0.0 never does.
def roll_collision_damage():
    chance = min(1.0, max(0.0, config.UAV_COLLISION_DAMAGE_MEAN))
    return 1 if config.SYSTEM_RANDOM.random() < chance else 0


# function that gives the fuel one step of flight costs a UAV, from the cells it actually covered and
# whether it ended the step parked on the home base. The cost is
#
#     idle + UAV_FUEL_BURN_PER_CELL * cells ** UAV_FUEL_SPEED_EXPONENT
#
# so with the exponent above 1 each extra cell of speed costs more than the last, and covering ground in
# one fast dash costs more than covering it slowly over several steps. A UAV that did not move pays the
# idle burn alone, since zero to any positive power is zero; one parked on the base pays nothing, which
# is what makes flying home to refuel worth the trip. Policies read this too, to work out how far the
# fuel they have left will take them, so the estimate and the charge cannot drift apart.
def fuel_burn_cost(cells_moved, at_base=False):
    idle = 0.0 if at_base else max(0.0, config.UAV_FUEL_IDLE_BURN)
    cells = max(0, int(cells_moved))
    return idle + max(0.0, config.UAV_FUEL_BURN_PER_CELL) * (cells ** max(0.0, config.UAV_FUEL_SPEED_EXPONENT))


# function that calculates the grade of influence of cell s' over cell s, based on a distance_limit
def distance_rate(s, s_, distance_limit):
    m_d = euclidean_distance(s[0], s[1], s_[0], s_[1])
    result = 0
    if m_d <= distance_limit:
        result = m_d ** -2.0
    return result
