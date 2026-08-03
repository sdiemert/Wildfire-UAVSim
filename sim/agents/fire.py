# python libraries

import functools

import mesa

# own python modules

import config

from sim import formulas
from sim.environment import Smoke


# Class Fire holds methods for managing Fire agents
class Fire(mesa.Agent):

    # constructor
    def __init__(self, unique_id, model, burning=False):
        super().__init__(unique_id, model)
        self.fuel = config.SYSTEM_RANDOM.randint(config.FUEL_BOTTOM_LIMIT, config.FUEL_UPPER_LIMIT)
        self.burning = burning
        self.next_burning_state = None
        self.moore = True
        self.radius = 3
        self.selected_dir = 0
        self.steps_counter = 0
        self.cell_prob = 0.0

        # firefighting extension: a cell that has been hit by water is immune for a while, and stays
        # flagged afterwards so that it can relight spontaneously
        self.immunity_counter = 0
        self.was_extinguished = False

        # smoke
        self.smoke = Smoke(fire_cell_fuel=self.fuel)

    # checks if the corresponding Fire agent is burning | True if burning, False if not
    def is_burning(self):
        return self.burning

    # checks whether this cell is currently immune to catching fire, after being hit by water
    def is_immune(self):
        return self.immunity_counter > 0

    # puts the fire in this cell out, and makes it immune for REIGNITION_DELAY steps. Returns True when
    # this call actually extinguished a burning cell, so that the caller can count it.
    def extinguish(self):
        was_burning = self.burning
        self.burning = False
        self.next_burning_state = False
        self.immunity_counter = config.REIGNITION_DELAY
        self.was_extinguished = True
        if config.ACTIVATE_SMOKE:
            self.smoke.smoke = False
        return was_burning

    # get the corresponding Fire agent remaining fuel | Integer value
    def get_fuel(self):
        return round(self.fuel)

    # get the corresponding Fire agent burning probability
    def get_prob(self):
        return self.cell_prob

    # function that calculates probability of cell s being burned in next time step (p_t+1(s)),
    # one cell at a time.
    #
    # The simulation does not call this any more: WildFireModel.update_fire_probabilities() works the
    # same quantity out for every cell of the grid at once (see sim/fire_spread.py), which is what
    # step() reads below. It is kept because it is the readable definition of the spread rule, and
    # because tests/test_fire_spread.py checks the vectorized version against it cell by cell. Change
    # the spread rule here and in sim/fire_spread.py together, and that test will hold you to it.
    def probability_of_fire(self):
        probs = []
        # if at least cell s has some fuel remaining
        if self.fuel > 0:
            # obtains adjacent cells for a given one (self.pos), based on a radius (self.radius)
            adjacent_cells = self.model.grid.get_neighborhood(
                self.pos, moore=self.moore, include_center=False, radius=self.radius
            )

            # iterates through each adjacent cell to calculate cell s probability of being burned
            # based on the adjacent ones
            for adjacent in adjacent_cells:
                # obtains cell content, such as different agents
                agents_in_adjacent = self.model.grid.get_cell_list_contents([adjacent])
                # iterates through each found agent of an adjacent cell
                for agent in agents_in_adjacent:
                    if type(agent) is Fire:
                        adjacent_burning = 1 if agent.is_burning() else 0
                        # calculates partial probability of burning cell s (self.pos), being influenced by adjacent (s')
                        aux_prob = formulas.distance_rate(self.pos, adjacent, self.radius) * adjacent_burning
                        # in this if statement, the wind logic occurs, by biasing the burning cell probability
                        if config.ACTIVATE_WIND and (adjacent_burning == 1):
                            # applies wind to the partial probability
                            aux_prob = self.model.wind.apply_wind(aux_prob, self.pos, agent.pos)
                        probs.append(1 - aux_prob)
            if len(probs) == 0:  # if a low tree density is set, this might happen, so it must be checked
                P = 0
            else:
                P = 1 - functools.reduce(lambda a, b: a * b, probs)
        else:
            P = 0
        return P

    # Mesa framework native method, which is overwritten, necessary for setting next state of the simulation
    def step(self):
        self.steps_counter += 1
        # the immunity left by a water drop is counted in simulation steps, not in fire updates, so it is
        # handled outside the FIRE_SPREAD_SPEED gate below. It is read before being decremented, so that a
        # drop with REIGNITION_DELAY = n protects the cell for n full steps.
        immune = config.ACTIVATE_FIREFIGHTING and self.immunity_counter > 0
        if immune:
            self.immunity_counter -= 1
        # make fire spread slower
        if self.steps_counter % config.FIRE_SPREAD_SPEED == 0:
            # if self.steps_counter == 26: # to model how the wind can suddenly change direction
            #     self.model.wind.wind_direction = 'south'
            # worked out for the whole grid before the schedule ran, so this is a lookup. The fuel
            # gate stays here, which keeps the model from having to mirror the fuel of every cell.
            self.cell_prob = 0.0 if self.fuel <= 0 else self.model.fire_prob[self.pos]
            generated = config.SYSTEM_RANDOM.random()
            # set next burning state
            if generated < self.cell_prob:
                self.next_burning_state = True
            else:
                self.next_burning_state = False
            # firefighting extension: a cell just hit by water cannot catch fire again yet. Once that wears
            # off it burns normally again, and may also relight on its own with a small probability.
            if config.ACTIVATE_FIREFIGHTING:
                if immune:
                    self.next_burning_state = False
                elif (self.was_extinguished and self.fuel > 0
                      and not self.next_burning_state
                      and config.SYSTEM_RANDOM.random() < config.SPONTANEOUS_REIGNITION_PROB):
                    self.next_burning_state = True
            # if possible, subtract BURNING_RATE from fuel of the corresponding cell
            if self.burning and self.fuel > 0:
                self.fuel = self.fuel - config.BURNING_RATE
            # smoke step
            if config.ACTIVATE_SMOKE:
                self.smoke.smoke_step(self.burning)

    # Mesa framework native method, which is overwritten, necessary for executing changes made in step() method. This
    # logic is required to not update the overall grid state until all cells step() method where executed.
    def advance(self):
        # make fire spread slower
        if self.steps_counter % config.FIRE_SPREAD_SPEED == 0:
            # only state changes are logged: a message per cell per step would mean hundreds of thousands
            # of records for a default sized grid
            if self.next_burning_state and not self.burning:
                self.model.log.debug("cell %s ignited (p=%.3f, fuel=%d)", self.pos, self.cell_prob, self.fuel)
            elif self.burning and self.fuel <= 0:
                self.model.log.debug("cell %s burnt out", self.pos)
            self.burning = self.next_burning_state
