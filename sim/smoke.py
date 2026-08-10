"""Where the smoke is: one plume field for the whole grid, in one convolution.

Each Fire cell owns a Smoke (see sim/environment.py) which says whether that cell is *raising* smoke. That
is the source. This module works out where the smoke then *is*, which is somewhere else: downwind of the
source, over ground that may hold no vegetation at all and may never burn. A cell the plume covers cannot
be observed, which is the whole point of the extension -- see UAV.observe() and ModelSensor.

The shape of the calculation is the one sim/fire_spread.py already uses for the fire. The contribution of
a source at offset (dx, dy) depends on the offset alone, so the density of every cell at once is a
convolution of the source mask with a fixed kernel:

    density(s) = SUM over offsets (dx, dy) of  K[dx, dy] * smoking[s + (dx, dy)]

    with K[dx, dy] = cell_weight(dx, dy, SMOKE_DRIFT_RADIUS, SMOKE_MU, direction)

cell_weight() and on_wind() are imported from sim/fire_spread.py rather than restated, so that the fire and
the smoke cannot come to disagree about which way is downwind.

Four things differ from the fire, each of them on purpose.

  * **A plain sum, clipped, rather than 1 - exp(SUM of logs).** The fire's log space form is there because
    ignition is 1 - PRODUCT(1 - w) over independent chances of one event. A density is an amount of stuff,
    not a probability of anything, so the honest form is the weighted sum itself, clipped into [0, 1] where
    several sources pile up. It is also the form a requirement can be written against.

  * **A source obscures itself.** cell_weight() answers 0 at distance 0, because a burning cell does not
    ignite itself. A smoking cell is certainly in its own smoke, so K[0, 0] is set to 1 outright.

  * **Composed wind is blended, not drawn.** FireSpread tosses a coin per cell per offset, because an
    ignition either happened downwind or it did not. Smoke hangs about for many steps and so sits in the
    average of the wind that blew over it, which is one fixed kernel: FIRST_DIR_PROB of the first
    direction's, the rest of the second's. That keeps this module free of randomness altogether -- it takes
    nothing from SYSTEM_RANDOM in any wind mode, so seeded runs reproduce exactly as they did before it
    existed.

  * **Occlusion is a threshold, not a roll.** A cell is opaque when its density reaches
    SMOKE_OCCLUSION_THRESHOLD. Deterministic, so the two observe() calls a UAV gets in one step cannot
    disagree about what it could see.

What the numbers come to, at the shipped SMOKE_MU = 0.9. cell_weight is distance ** -2, biased to
w + mu(1 - w) downwind and w - mu*w everywhere else, so the wind decides almost everything. Downwind the
weight barely decays with distance at all -- 1.0 at one cell, 0.925 at two, 0.903 at six -- while one cell
crosswind is 0.1 and one cell diagonally is 0.05. At the shipped threshold of 0.5 a lone source therefore
obscures itself and the column of cells downwind of it, out to SMOKE_DRIFT_RADIUS, and nothing else.

That a lone source casts a plume one cell wide reads as a wart in isolation and is not one in practice,
because a fire is a front rather than a cell: every smoking cell of it casts its own column, and the union
is a plume as wide as the front that raised it. Off the axis the density is a sum of several sources at
0.05 to 0.1 apiece, so a wider front also smears a little further sideways, which is the right way round.
The escape hatch, if the column ever shows up as an artefact, is a smoke specific on_wind() treating any
offset with a downwind component as downwind, which would give a cone -- deliberately not done here,
because it would fork the wind model into two definitions free to drift apart, and sharing one is what
keeps this module to a hundred lines.

The fire, for comparison, runs at MU = 0.5 over a radius of 3: half the lean, a third of the reach.
"""

# python libraries

import numpy

# own python modules

# imported as a module rather than with 'from config import *', so that a runner which overrides the
# constants (see sim/cli/) is picked up when a SmokeField is built
import config

from sim.fire_spread import cell_weight


# builds the linear kernel for one wind direction, or for no wind when direction is None. Entry
# [dx + radius, dy + radius] is the density a source at offset (dx, dy) contributes to a cell.
#
# fire_spread.build_kernel() cannot be reused: it takes the logarithm, which is the fire's product rule and
# not this one, and it collapses everything at weight 1 to a stand-in for log(0).
def build_smoke_kernel(radius, mu, direction=None):
    kernel = numpy.zeros((2 * radius + 1, 2 * radius + 1))
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            kernel[dx + radius, dy + radius] = cell_weight(dx, dy, radius, mu, direction)
    # a cell raising smoke is in its own smoke. cell_weight() answers 0 here, because it is written for a
    # fire deciding whether a neighbour lights it and no cell lights itself
    kernel[radius, radius] = 1.0
    return kernel


# Class SmokeField evaluates the smoke density of every cell of the grid at once, and the mask of cells too
# thick with it to see through. It reads the wind and smoke settings when it is built, so a model rebuilds
# one in reset() and any override applied by a runner takes effect.
class SmokeField:

    # constructor. 'radius' and 'mu' default to the configured plume settings; they are arguments so that a
    # test can build a field without reaching for the whole config.
    def __init__(self, height, width, radius=None, mu=None, threshold=None):
        self.height = height
        self.width = width
        self.radius = config.SMOKE_DRIFT_RADIUS if radius is None else radius
        self.mu = config.SMOKE_MU if mu is None else mu
        self.threshold = config.SMOKE_OCCLUSION_THRESHOLD if threshold is None else threshold

        radius = self.radius
        if not config.ACTIVATE_WIND:
            # one kernel, no wind bias anywhere: a symmetric blob around every source
            self.kernel = build_smoke_kernel(radius, self.mu)
        elif config.FIXED_WIND:
            self.kernel = build_smoke_kernel(radius, self.mu, config.WIND_DIRECTION)
        else:
            # composed wind, blended once rather than drawn per cell -- see the module docstring. The blend
            # is of the kernels and not of two finished density fields, so that there is exactly one kernel
            # to reason about and the clip below is applied once, to the total.
            first = build_smoke_kernel(radius, self.mu, config.FIRST_DIR)
            second = build_smoke_kernel(radius, self.mu, config.SECOND_DIR)
            share = config.FIRST_DIR_PROB
            self.kernel = (share * first) + ((1.0 - share) * second)

        # offsets that contribute at all, so the evaluation loop skips the corners of the window (which lie
        # beyond the radius) and anything the wind blew out entirely
        self.offsets = [
            (dx, dy)
            for dx in range(-radius, radius + 1)
            for dy in range(-radius, radius + 1)
            if self.kernel[dx + radius, dy + radius] != 0
        ]

    # the smoke density of every cell, from the mask of the cells raising smoke. The mask is indexed [x, y]
    # like the Mesa grid positions, and is zero padded because the grid is not a torus, which reproduces the
    # clipping get_neighborhood() does at the edges. Clipped into [0, 1]: several sources reaching one cell
    # make it opaque, not more than opaque.
    def density(self, smoking):
        radius = self.radius
        height, width = self.height, self.width

        padded = numpy.pad(numpy.asarray(smoking, dtype=float), radius)
        accumulated = numpy.zeros((height, width))

        for dx, dy in self.offsets:
            shifted = padded[radius + dx:radius + dx + height, radius + dy:radius + dy + width]
            accumulated += self.kernel[dx + radius, dy + radius] * shifted

        return numpy.clip(accumulated, 0.0, 1.0)

    # the cells nobody can see into or through, as a boolean mask indexed [x, y]
    def opaque(self, smoking):
        return self.density(smoking) >= self.threshold
