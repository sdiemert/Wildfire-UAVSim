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
import random

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


# function that draws one positioning error offset from SYSTEM_RANDOM: a uniform integer per axis in
# [-magnitude, +magnitude], in cells. This is where a UAV's fixed bias comes from, drawn once when it is
# created, and the magnitude is a parameter rather than read from config so that the per step jitter below
# can share the arithmetic.
#
# Answers (0, 0) whenever the extension is switched off or the magnitude is zero, and -- the part that
# matters -- takes no draw at all in that case. A run without positioning error has to consume exactly the
# SYSTEM_RANDOM sequence it consumed before this existed, or every seeded result in the project moves the
# day the extension is merged.
def draw_position_offset(magnitude, source=None):
    if not config.ACTIVATE_POSITION_ERROR or magnitude <= 0:
        return 0, 0

    generator = config.SYSTEM_RANDOM if source is None else source
    limit = int(magnitude)
    return (generator.randint(-limit, limit), generator.randint(-limit, limit))


# function that gives the per step jitter in one UAV's fix: a uniform integer per axis in
# [-magnitude, +magnitude], in cells, for the UAV identified by 'seed' on step 'step'.
#
# Deliberately *not* a draw from SYSTEM_RANDOM. It is a pure function of the UAV and the step number, worked
# out from a generator seeded on the pair, so that asking a UAV where it thinks it is has no effect on the
# rest of the simulation. That matters because the answer is wanted in places that must not disturb a run:
# the web interface renders the panel between steps, a test may want the fix of one UAV on its own, and the
# managing system reads the fleet at a different point in the step from the policies. Taking the jitter from
# the shared generator would make all of those change the run they were only meant to be looking at -- the
# same simulation watched in a browser would come out differently from one in headless.py.
#
# 'seed' is drawn from SYSTEM_RANDOM once per UAV when it is created, which is what keeps a whole run
# reproducible from a single seed. It is combined with the step as text because seeding a generator with a
# string goes through sha512, so nearby seeds give unrelated sequences and neighbouring steps of one UAV are
# no more alike than any other pair.
def position_noise(seed, step, magnitude):
    if not config.ACTIVATE_POSITION_ERROR or magnitude <= 0:
        return 0, 0

    return draw_position_offset(magnitude, source=random.Random(f"{seed}:{step}"))


# function that gives the fuel one step of flight costs a UAV, from the cells it actually covered, the
# water it was carrying while it covered them and whether it ended the step parked on the home base. The
# cost is
#
#     (idle + UAV_FUEL_BURN_PER_CELL * cells ** UAV_FUEL_SPEED_EXPONENT)
#         * (1 + UAV_FUEL_WATER_PENALTY * water_load)
#
# so with the exponent above 1 each extra cell of speed costs more than the last, and covering ground in
# one fast dash costs more than covering it slowly over several steps. A UAV that did not move pays the
# idle burn alone, since zero to any positive power is zero; one parked on the base pays nothing, which
# is what makes flying home to refuel worth the trip.
#
# 'water_load' is the share of a full load aboard, in [0, 1], and multiplies the whole cost rather than
# the distance alone: carrying mass costs lift whether or not the UAV is going anywhere, so a loaded UAV
# holding station burns more than an empty one doing the same. The base waiver survives it, since a
# multiple of zero is zero. Policies read all of this too, to work out how far the fuel they have left
# will take them, so the estimate and the charge cannot drift apart -- Observation.water_fraction() is
# what a policy passes here.
def fuel_burn_cost(cells_moved, at_base=False, water_load=0.0):
    idle = 0.0 if at_base else max(0.0, config.UAV_FUEL_IDLE_BURN)
    cells = max(0, int(cells_moved))
    flight = idle + max(0.0, config.UAV_FUEL_BURN_PER_CELL) * (cells ** max(0.0, config.UAV_FUEL_SPEED_EXPONENT))
    payload = max(0.0, min(1.0, water_load))
    return flight * (1.0 + max(0.0, config.UAV_FUEL_WATER_PENALTY) * payload)


# function that calculates the grade of influence of cell s' over cell s, based on a distance_limit
def distance_rate(s, s_, distance_limit):
    m_d = euclidean_distance(s[0], s[1], s_[0], s_[1])
    result = 0
    if m_d <= distance_limit:
        result = m_d ** -2.0
    return result
