"""The wind, and the cells raising smoke.

Neither is a mesa.Agent: they hold no cell on the grid and are not stepped by the scheduler. The wind is a
single object the model owns, holding the one direction blowing over the whole grid, and a Smoke belongs to
the Fire cell that made it, which steps it. They live together here because both are environmental
conditions layered over the fire rather than things standing on the map.

The wind is stepped by the model rather than by the scheduler, because it has to turn cleanly between
simulation steps: the fire field is built before the scheduler runs and the smoke field after it, and both
have to be told the same direction for the step they belong to.

Smoke here is only the *emitter*: one timer per cell, which says whether that cell is raising smoke and for
how much longer. Where the smoke goes is a separate question with a separate answer, because it does not
stay over the cell that raised it -- it blows downwind, over ground that may hold nothing and may never
burn, and the cells it covers cannot be observed at all. That field is worked out for the whole grid at
once in sim/smoke.py, from the mask of the cells this class turns on.
"""

# own python modules

import config


# Class Smoke holds methods for managing smoke functionality
class Smoke:

    # constructor
    def __init__(self, fire_cell_fuel):
        self.smoke = False
        self.dispelling_counter_start_value = fire_cell_fuel
        self.dispelling_lower_bound_start_value = config.SMOKE_PRE_DISPELLING_COUNTER
        self.dispelling_lower_bound = self.dispelling_lower_bound_start_value
        self.dispelling_counter = self.dispelling_counter_start_value

    # it gets the remaining dispelling counter value
    def get_dispelling_counter_value(self):
        return self.dispelling_counter

    # it gets the remaining pre-dispelling counter value
    def get_dispelling_counter_start_value(self):
        return self.dispelling_counter_start_value

    # it gets if smoke is active | True if active, False if not
    def is_smoke_active(self):
        return self.smoke

    # it subtracts one from dispelling counter value
    def subtract_dispelling_counter(self):
        self.dispelling_counter -= 1

    # function that updates smoke state and its counters based on certain conditions
    def smoke_step(self, burning):
        # if smoke isn't activated yet:
        if not self.smoke and self.dispelling_counter == self.dispelling_counter_start_value:
            # if pre-dispelling smoke counter can start (cell is burning), or if it already started:
            if ((burning and self.dispelling_lower_bound == self.dispelling_lower_bound_start_value) or
                    (0 < self.dispelling_lower_bound < self.dispelling_lower_bound_start_value)):
                # subtract from pre-dispelling counter (on the way to start smoke)
                self.dispelling_lower_bound -= 1
            # if pre-dispelling smoke counter already finished:
            elif self.dispelling_lower_bound == 0:
                # start smoke counter (activate smoke)
                self.smoke = True
        # if smoke can start, or if it already started
        elif self.smoke:
            # if dispelling counter can start, or if it already started
            if 0 < self.dispelling_counter <= self.dispelling_counter_start_value:
                # subtract from dispelling counter
                self.subtract_dispelling_counter()
            # if dispelling counter already finished
            elif self.dispelling_counter == 0:
                # smoke counter is stopped
                self.smoke = False


# Class Wind holds the direction blowing over the whole grid, and turns it on a clock.
#
# One direction at a time, everywhere: the wind is a property of the day rather than of a cell, so the
# fire and the smoke of a given step are both worked out from the single value this object is holding. It
# is the model that owns it and ticks it (see WildFireModel.step()), because the turn has to land between
# steps rather than part way through one -- update_fire_probabilities() and update_smoke() sit either side
# of the scheduler, and a wind that turned between them would smoke in a direction it never burned in.
#
# This used to be a per cell coin toss between FIRST_DIR and SECOND_DIR, redrawn for every cell and every
# neighbour of it. See the ## Wind section of config.py for why it is not any more.
class Wind:

    # constructor. The opening direction is drawn here, so a model has a wind before it builds anything
    # that reads one.
    def __init__(self):
        self.directions = config.wind_directions()
        self.variability = config.WIND_VARIABILITY
        self.steps_held = 0
        # how many times a fresh direction has been drawn, which is not how many times the wind has
        # actually changed: a draw is free to land on the direction already blowing
        self.redraws = 0
        self.wind_direction = self.directions[0] if self.directions else None
        # a single direction is not a draw, and neither is no wind at all. Skipping them keeps those runs
        # taking nothing from SYSTEM_RANDOM, which is what lets a seeded fixed wind run reproduce results
        # from before the wind could turn -- and what makes a one entry list genuinely free.
        if len(self.directions) > 1:
            self.change_direction()

    # whether the wind can ever turn. A one entry list and a still day are both settled for the whole run,
    # so the model can stop asking.
    def is_variable(self):
        return len(self.directions) > 1 and self.variability is not None

    # draws a fresh direction, uniformly over the configured list
    def change_direction(self):
        self.wind_direction = config.SYSTEM_RANDOM.choice(self.directions)

    # one simulation step of weather. The direction is held for WIND_VARIABILITY steps and then drawn
    # again; with WIND_VARIABILITY None it is held for the whole run, which is the "randomised once per
    # run" case. Returns whether the wind turned, which is only used for logging.
    def step(self):
        if not self.is_variable():
            return False

        self.steps_held += 1
        if self.steps_held < self.variability:
            return False

        previous = self.wind_direction
        self.change_direction()
        self.steps_held = 0
        self.redraws += 1
        return self.wind_direction != previous

    # function to apply wind to partial burning probability of cell s (relative_center_pos),
    # caused by cell s' (adjacent_pos).
    #
    # This is the readable definition of what the wind does to a probability. Nothing calls it during a run
    # -- the live spread is the convolution in sim/fire_spread.py, which cannot be read as a definition of
    # anything -- but tests/test_fire_spread.py checks the kernel against it, offset by offset, so the two
    # cannot come apart.
    def apply_wind(self, aux_prob, relative_center_pos, adjacent_pos):
        # a neighbour with no influence to begin with keeps none. The wind biases a chance that exists; it
        # does not manufacture one out of a cell too far away to matter. distance_rate() answers 0 beyond
        # the spread radius, and the Moore window reaches past it at the corners -- without this line an
        # on-wind corner would be lifted from 0 to MU, which is a burning cell at distance 4.24 setting
        # light to one at a probability of 0.5. It never showed under a cardinal wind, whose ray misses
        # the corners entirely, and shows under every diagonal, whose ray runs straight through one.
        # cell_weight() in sim/fire_spread.py has always returned before the bias for the same reason.
        if aux_prob <= 0:
            return aux_prob
        if self.is_on_wind_direction(relative_center_pos, adjacent_pos):
            aux_prob = aux_prob + (config.MU * (1 - aux_prob))  # part of 1 - 'aux_prob' probability is added, depending on mu
        else:
            aux_prob = aux_prob - (config.MU * aux_prob)  # part of 'aux_prob' probability is removed, depending on mu
        return aux_prob

    # function that checks if cell located in relative_center_pos is on wind direction, influenced by cell located
    # in adjacent_pos.
    #
    # The cell is downwind of its neighbour when the step from neighbour to cell runs along the heading, so
    # the offset the other way -- neighbour minus cell -- is a whole number of steps *against* it. Written
    # out for all eight directions this would be eight branches of the same arithmetic; the heading table in
    # config.py is that arithmetic once.
    def is_on_wind_direction(self, relative_center_pos, adjacent_pos):
        if self.wind_direction is None:
            return False

        heading = config.WIND_HEADINGS[self.wind_direction]
        dx = adjacent_pos[0] - relative_center_pos[0]
        dy = adjacent_pos[1] - relative_center_pos[1]
        return on_heading(heading, dx, dy)


# whether a neighbour at offset (dx, dy) lies on the ray the wind blows along, which is to say at
# (-k * ux, -k * uy) for a whole number of steps k >= 1. Shared by Wind above and by
# fire_spread.on_wind(), so that the definition of downwind exists once.
def on_heading(heading, dx, dy):
    ux, uy = heading
    # the offset has to be a whole number of steps back along the heading, and the same number of them on
    # both axes: for a diagonal that is dx == -k * ux and dy == -k * uy with one k, which rules out the
    # off-axis neighbours a pair of independent checks would let through
    if ux == 0:
        return dx == 0 and dy != 0 and dy * uy < 0
    if uy == 0:
        return dy == 0 and dx != 0 and dx * ux < 0
    return dx * ux < 0 and dy * uy < 0 and abs(dx) == abs(dy)
