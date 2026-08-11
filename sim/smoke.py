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

  * **The plume is rebuilt from scratch every step, so it turns with the wind.** There is no carried over
    density: the field is a function of where the sources are now and which way the wind is blowing now,
    so when the wind turns the whole plume swings with it that step rather than bending gradually. That is
    a simplification, and a visible one on screen at low WIND_VARIABILITY. It is the same simplification
    the fire makes -- a burning cell's influence depends on the current wind and not on the wind of the
    step it caught in -- and keeping the two the same is worth more here than a smoke specific memory
    would be. This module still takes nothing at all from SYSTEM_RANDOM.

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

        # one kernel per direction the wind may blow, and the unbiased one -- a symmetric blob around every
        # source -- under None, for a still day or a caller that names no direction. Built up front for the
        # same reason FireSpread does it: a turning wind then costs a dictionary lookup rather than a
        # rebuild. The plume radius is larger than the fire's, so these are the bigger arrays of the two,
        # and eight of them is still nothing.
        self.kernels = {None: build_smoke_kernel(radius, self.mu)}
        for direction in config.wind_directions():
            self.kernels[direction] = build_smoke_kernel(radius, self.mu, direction)

        # offsets that contribute at all, so the evaluation loop skips the corners of the window (which lie
        # beyond the radius) and anything the wind blew out entirely
        self.offsets = {
            direction: [
                (dx, dy)
                for dx in range(-radius, radius + 1)
                for dy in range(-radius, radius + 1)
                if kernel[dx + radius, dy + radius] != 0
            ]
            for direction, kernel in self.kernels.items()
        }

    # the kernel for a direction. None, and a direction the wind was never configured to blow, both fall
    # back to the unbiased blob, matching FireSpread.kernel_for().
    def kernel_for(self, direction):
        if direction is None:
            return self.kernels[None], self.offsets[None]
        name = direction.upper()
        if name not in self.kernels:
            if name not in config.WIND_HEADINGS:
                raise ValueError(f"unknown wind direction {direction!r}, "
                                 f"expected one of {config.WIND_DIRECTIONS}")
            return self.kernels[None], self.offsets[None]
        return self.kernels[name], self.offsets[name]

    # the smoke density of every cell, from the mask of the cells raising smoke and the wind blowing this
    # step. The mask is indexed [x, y] like the Mesa grid positions, and is zero padded because the grid is
    # not a torus, which reproduces the clipping get_neighborhood() does at the edges. Clipped into [0, 1]:
    # several sources reaching one cell make it opaque, not more than opaque.
    def density(self, smoking, direction=None):
        radius = self.radius
        height, width = self.height, self.width
        kernel, offsets = self.kernel_for(direction)

        padded = numpy.pad(numpy.asarray(smoking, dtype=float), radius)
        accumulated = numpy.zeros((height, width))

        for dx, dy in offsets:
            shifted = padded[radius + dx:radius + dx + height, radius + dy:radius + dy + width]
            accumulated += kernel[dx + radius, dy + radius] * shifted

        return numpy.clip(accumulated, 0.0, 1.0)

    # the cells nobody can see into or through, as a boolean mask indexed [x, y]
    def opaque(self, smoking, direction=None):
        return self.density(smoking, direction) >= self.threshold
