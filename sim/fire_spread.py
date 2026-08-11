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

The kernels are built once per model, and each step costs one pass over the grid instead of a Python
loop over every cell times every neighbour.

One kernel is built per direction the wind may blow (see config.WIND_DIRECTION), which is at most eight
small arrays, and probability_field() is handed the one blowing now. Building them all up front rather
than rebuilding on each turn keeps a turning wind free: the cost is a couple of hundred logarithms at
construction, against a rebuild every WIND_VARIABILITY steps.

Reproducibility: this module consumes no randomness at all, in any wind mode, so a seeded run is decided
entirely by the fire and the UAVs. It used to draw an array per offset per step under the old composed
wind, which tossed a coin per cell and per neighbour to pick between two directions; the wind is now one
direction over the whole grid and the only draw it takes is Wind.change_direction(), once per turn.
"""

# python libraries

import math

import numpy

# own python modules

# imported as a module rather than with 'from config import *', so that a runner which overrides the
# constants (see sim/cli/) is picked up when a FireSpread is built
import config

from sim.environment import on_heading


# stand-in for log(0), used for the four orthogonal neighbours, whose w is exactly 1 and which
# therefore set P = 1 outright. A diagonal neighbour reaches it too once the wind is strong enough to
# carry its 0.5 the rest of the way, which is to say at MU = 1. It only has to be low enough that
# 1 - exp(NEG_INF) rounds to 1.0:
# exp(-50) is 2e-22, far below the 2e-16 resolution of a float64 near 1. A true -inf would be
# multiplied by a zero of the burning mask and give nan.
NEG_INF = -50.0

# the eight wind directions, and the offsets they favour. is_on_wind_direction(s, s') in sim/environment.py
# compares the cell with its neighbour; rewriting it on the offset (dx, dy) = s' - s gives, for
# 'EAST' (s[0] > s'[0] and s[1] == s'[1]) the neighbours lying to the west, and so on. Taken from
# config.py, which validates the wind settings against the same tuple, so the two cannot drift apart.
WIND_DIRECTIONS = config.WIND_DIRECTIONS


# checks whether a neighbour at offset (dx, dy) from a cell pushes fire into it under this wind. The rule
# itself lives in sim/environment.py beside the Wind, so that the convolution here and the readable per
# cell definition there cannot come to disagree about which way is downwind.
def on_wind(direction, dx, dy):
    try:
        heading = config.WIND_HEADINGS[direction.upper()]
    except (AttributeError, KeyError):
        raise ValueError(f"unknown wind direction {direction!r}, expected one of {WIND_DIRECTIONS}") from None
    return on_heading(heading, dx, dy)


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


# the offsets a kernel contributes at all, so that the evaluation loop skips the corners of the window
# (which lie beyond the radius) and anything the wind zeroed out
def contributing_offsets(kernel, radius):
    return [
        (dx, dy)
        for dx in range(-radius, radius + 1)
        for dy in range(-radius, radius + 1)
        if kernel[dx + radius, dy + radius] != 0
    ]


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

        mu = config.MU
        self.directions = config.wind_directions()

        # one kernel per direction the wind may blow, and always the unbiased one under None, so that a
        # caller which passes no direction -- a test, or a run with the wind switched off -- gets an
        # answer rather than a KeyError. Each is paired with the offsets it actually contributes at.
        self.kernels = {None: build_kernel(radius, mu)}
        for direction in self.directions:
            self.kernels[direction] = build_kernel(radius, mu, direction)
        self.offsets = {
            direction: contributing_offsets(kernel, radius)
            for direction, kernel in self.kernels.items()
        }

    # checks that the Fire agents really do share the radius and neighbourhood this kernel was built
    # for. A per agent radius would make the whole approach wrong, so it fails loudly instead.
    def assert_matches(self, fire_agents):
        for agent in fire_agents:
            if agent.radius != self.radius or bool(agent.moore) != self.moore:
                raise ValueError(
                    f"Fire agent at {agent.pos} uses radius={agent.radius} moore={agent.moore}, "
                    f"but the spread kernel was built for radius={self.radius} moore={self.moore}"
                )

    # the kernel for a direction, by way of the one place that turns an unknown direction into a clear
    # error. None, and a direction the wind was never configured to blow, both fall back to no bias --
    # the first deliberately, the second because a model that has switched the wind off mid run has no
    # kernel to offer and an unbiased fire is the honest answer.
    def kernel_for(self, direction):
        if direction is None:
            return self.kernels[None], self.offsets[None]
        name = direction.upper()
        if name not in self.kernels:
            if name not in config.WIND_HEADINGS:
                raise ValueError(f"unknown wind direction {direction!r}, "
                                 f"expected one of {WIND_DIRECTIONS}")
            return self.kernels[None], self.offsets[None]
        return self.kernels[name], self.offsets[name]

    # gives the ignition probability of every cell, from the burning mask of the whole grid, under the
    # wind blowing this step. The mask is indexed [x, y] like the Mesa grid positions, and is zero padded
    # because the grid is not a torus, which reproduces the clipping get_neighborhood() does at the edges.
    #
    # The direction is an argument rather than state, so that this object holds no opinion about what the
    # weather is doing: the model owns the Wind and hands over whichever direction it is holding, and a
    # test can drive one directly without building a model at all.
    def probability_field(self, burning, direction=None):
        radius = self.radius
        height, width = self.height, self.width
        kernel, offsets = self.kernel_for(direction)

        padded = numpy.pad(numpy.asarray(burning, dtype=float), radius)
        accumulated = numpy.zeros((height, width))

        for dx, dy in offsets:
            shifted = padded[radius + dx:radius + dx + height, radius + dy:radius + dy + width]
            accumulated += kernel[dx + radius, dy + radius] * shifted

        return 1.0 - numpy.exp(accumulated)
