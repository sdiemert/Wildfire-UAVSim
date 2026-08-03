"""Vectorized fire spread: every cell's ignition probability in one convolution.

The per cell calculation in Fire.probability_of_fire() (see sim/agents/fire.py) works out, for a cell s:

    P(s) = 1 - PRODUCT over burning neighbours s' of (1 - w(s, s'))

where w is distance_rate() from config.py, optionally biased by the wind. Two properties make the
whole grid computable at once:

  * a neighbour that is not burning contributes a factor of exactly 1, and a cell holding no
    vegetation is simply absent from the product, so only the burning cells matter;
  * w depends on the offset s' - s alone, never on the cells themselves.

Taking logarithms turns the product into a sum over offsets, which is a convolution of the burning
mask with a fixed kernel:

    log(1 - P(s)) = SUM over offsets (dx, dy) of  K[dx, dy] * burning[x + dx, y + dy]

    with K[dx, dy] = log(1 - w(dx, dy))

The kernel is built once per model, and each step costs one pass over the grid instead of a Python
loop over every cell times every neighbour.

Reproducibility: with the wind switched off, or with FIXED_WIND, this consumes no randomness at all,
exactly like the per cell version, so seeded runs reproduce the old results step for step. With
composed wind (FIXED_WIND = False) the old code drew from SYSTEM_RANDOM once per cell/neighbour pair
inside Wind.change_direction(); this module draws one array per affected offset instead. The
distribution is the same, the stream of draws is not, so seeded composed wind runs will not match
results produced before this module existed.
"""

# python libraries

import math

import numpy

# own python modules

# imported as a module rather than with 'from config import *', so that a runner which overrides the
# constants (see sim/cli/) is picked up when a FireSpread is built
import config


# stand-in for log(0), used for the four orthogonal neighbours, whose w is exactly 1 and which
# therefore set P = 1 outright. It only has to be low enough that 1 - exp(NEG_INF) rounds to 1.0:
# exp(-50) is 2e-22, far below the 2e-16 resolution of a float64 near 1. A true -inf would be
# multiplied by a zero of the burning mask and give nan.
NEG_INF = -50.0

# the four wind directions, and the offsets they favour. is_on_wind_direction(s, s') in sim/environment.py
# compares the cell with its neighbour; rewriting it on the offset (dx, dy) = s' - s gives, for
# 'east' (s[0] > s'[0] and s[1] == s'[1]) the neighbours lying to the west, and so on. Taken from
# config.py, which validates the wind settings against the same tuple, so the two cannot drift apart.
WIND_DIRECTIONS = config.WIND_DIRECTIONS


# checks whether a neighbour at offset (dx, dy) from a cell pushes fire into it under this wind
def on_wind(direction, dx, dy):
    if direction == "east":
        return dx < 0 and dy == 0
    if direction == "west":
        return dx > 0 and dy == 0
    if direction == "north":
        return dx == 0 and dy < 0
    if direction == "south":
        return dx == 0 and dy > 0
    raise ValueError(f"unknown wind direction {direction!r}, expected one of {WIND_DIRECTIONS}")


# the influence a burning neighbour at offset (dx, dy) has on a cell, before the logarithm. This is
# distance_rate() from config.py, followed by Wind.apply_wind() when a direction is given.
def cell_weight(dx, dy, radius, mu, direction=None):
    distance = math.hypot(dx, dy)
    if distance == 0 or distance > radius:
        return 0.0

    weight = distance ** -2.0
    if direction is not None:
        if on_wind(direction, dx, dy):
            weight = weight + (mu * (1 - weight))
        else:
            weight = weight - (mu * weight)
    return weight


# builds the log space kernel for one wind direction, or for no wind when direction is None. Entry
# [dx + radius, dy + radius] is the contribution of a burning neighbour at offset (dx, dy).
def build_kernel(radius, mu, direction=None):
    kernel = numpy.zeros((2 * radius + 1, 2 * radius + 1))
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            weight = cell_weight(dx, dy, radius, mu, direction)
            if weight <= 0:
                continue  # out of range, or blown out entirely by the wind
            kernel[dx + radius, dy + radius] = NEG_INF if weight >= 1.0 else math.log1p(-weight)
    return kernel


# the offsets at which two wind directions disagree. Only these need a per cell coin toss under
# composed wind; everywhere else the two kernels hold the same value.
def mixed_offsets(kernel_first, kernel_second, radius):
    offsets = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if kernel_first[dx + radius, dy + radius] != kernel_second[dx + radius, dy + radius]:
                offsets.append((dx, dy))
    return offsets


# Class FireSpread evaluates the ignition probability of every cell of the grid at once. It reads the
# wind settings when it is built, so a model rebuilds one in reset() and any override applied by a
# runner takes effect.
class FireSpread:

    # constructor. 'radius' and 'moore' must match what the Fire agents use (see sim/agents/fire.py), which
    # assert_matches() checks against the live agents.
    def __init__(self, height, width, radius=3, moore=True):
        if not moore:
            raise ValueError("only the Moore neighbourhood is vectorized")

        self.height = height
        self.width = width
        self.radius = radius
        self.moore = moore

        self.wind_active = bool(config.ACTIVATE_WIND)
        self.fixed_wind = bool(config.FIXED_WIND)
        self.first_dir_prob = config.FIRST_DIR_PROB if not self.fixed_wind else 1.0

        mu = config.MU
        if not self.wind_active:
            # one kernel, no wind bias anywhere
            self.kernel = build_kernel(radius, mu)
            self.kernel_second = None
            self.mixed = set()
        elif self.fixed_wind:
            self.kernel = build_kernel(radius, mu, config.WIND_DIRECTION)
            self.kernel_second = None
            self.mixed = set()
        else:
            # composed wind: each cell/neighbour pair independently blows FIRST_DIR with probability
            # FIRST_DIR_PROB, otherwise SECOND_DIR. The two kernels differ on only a handful of
            # offsets, which are the ones that need a random draw per step.
            self.kernel = build_kernel(radius, mu, config.FIRST_DIR)
            self.kernel_second = build_kernel(radius, mu, config.SECOND_DIR)
            self.mixed = set(mixed_offsets(self.kernel, self.kernel_second, radius))

        # the per cell wind draws are the only randomness this module needs, and they are only
        # needed under composed wind. The generator is seeded from SYSTEM_RANDOM, so a runner that
        # seeds the simulation (see sim/cli/) makes them reproducible too. It is built lazily so
        # that the other two wind modes consume nothing from SYSTEM_RANDOM and leave the stream of
        # draws, and therefore seeded runs, exactly as they were before this module existed.
        self.rng = numpy.random.default_rng(config.SYSTEM_RANDOM.getrandbits(64)) if self.mixed else None

        # offsets that contribute at all, so that the evaluation loop skips the corners of the
        # window (which lie beyond the radius) and anything the wind zeroed out
        self.offsets = [
            (dx, dy)
            for dx in range(-radius, radius + 1)
            for dy in range(-radius, radius + 1)
            if self.kernel[dx + radius, dy + radius] != 0
            or (self.kernel_second is not None and self.kernel_second[dx + radius, dy + radius] != 0)
        ]

    # checks that the Fire agents really do share the radius and neighbourhood this kernel was built
    # for. A per agent radius would make the whole approach wrong, so it fails loudly instead.
    def assert_matches(self, fire_agents):
        for agent in fire_agents:
            if agent.radius != self.radius or bool(agent.moore) != self.moore:
                raise ValueError(
                    f"Fire agent at {agent.pos} uses radius={agent.radius} moore={agent.moore}, "
                    f"but the spread kernel was built for radius={self.radius} moore={self.moore}"
                )

    # gives the ignition probability of every cell, from the burning mask of the whole grid. The
    # mask is indexed [x, y] like the Mesa grid positions, and is zero padded because the grid is
    # not a torus, which reproduces the clipping get_neighborhood() does at the edges.
    def probability_field(self, burning):
        radius = self.radius
        height, width = self.height, self.width

        padded = numpy.pad(numpy.asarray(burning, dtype=float), radius)
        accumulated = numpy.zeros((height, width))

        for dx, dy in self.offsets:
            shifted = padded[radius + dx:radius + dx + height, radius + dy:radius + dy + width]
            weight = self.kernel[dx + radius, dy + radius]

            if (dx, dy) in self.mixed:
                # composed wind, on an offset the two directions disagree about: draw which way the
                # wind blows for each cell of the grid, as change_direction() did per pair. Each
                # offset gets its own draw, because the old code redrew for every pair.
                second = self.kernel_second[dx + radius, dy + radius]
                blows_first = self.rng.random((height, width)) < self.first_dir_prob
                accumulated += numpy.where(blows_first, weight, second) * shifted
            else:
                accumulated += weight * shifted

        return 1.0 - numpy.exp(accumulated)
