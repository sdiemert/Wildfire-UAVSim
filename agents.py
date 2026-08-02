# python libraries

import mesa
import functools

# own python modules

from policy import Observation

from config import *


# Class Fire holds methods for managing Fire agents
class Fire(mesa.Agent):

    # constructor
    def __init__(self, unique_id, model, burning=False):
        super().__init__(unique_id, model)
        self.fuel = random.randint(FUEL_BOTTOM_LIMIT, FUEL_UPPER_LIMIT)
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
        self.immunity_counter = REIGNITION_DELAY
        self.was_extinguished = True
        if ACTIVATE_SMOKE:
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
    # same quantity out for every cell of the grid at once (see fire_spread.py), which is what
    # step() reads below. It is kept because it is the readable definition of the spread rule, and
    # because tests/test_fire_spread.py checks the vectorized version against it cell by cell. Change
    # the spread rule here and in fire_spread.py together, and that test will hold you to it.
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
                        aux_prob = distance_rate(self.pos, adjacent, self.radius) * adjacent_burning
                        # in this if statement, the wind logic occurs, by biasing the burning cell probability
                        if ACTIVATE_WIND and (adjacent_burning == 1):
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
        immune = ACTIVATE_FIREFIGHTING and self.immunity_counter > 0
        if immune:
            self.immunity_counter -= 1
        # make fire spread slower
        if self.steps_counter % FIRE_SPREAD_SPEED == 0:
            # if self.steps_counter == 26: # to model how the wind can suddenly change direction
            #     self.model.wind.wind_direction = 'south'
            # worked out for the whole grid before the schedule ran, so this is a lookup. The fuel
            # gate stays here, which keeps the model from having to mirror the fuel of every cell.
            self.cell_prob = 0.0 if self.fuel <= 0 else self.model.fire_prob[self.pos]
            generated = random.random()
            # set next burning state
            if generated < self.cell_prob:
                self.next_burning_state = True
            else:
                self.next_burning_state = False
            # firefighting extension: a cell just hit by water cannot catch fire again yet. Once that wears
            # off it burns normally again, and may also relight on its own with a small probability.
            if ACTIVATE_FIREFIGHTING:
                if immune:
                    self.next_burning_state = False
                elif (self.was_extinguished and self.fuel > 0
                      and not self.next_burning_state
                      and random.random() < SPONTANEOUS_REIGNITION_PROB):
                    self.next_burning_state = True
            # if possible, subtract BURNING_RATE from fuel of the corresponding cell
            if self.burning and self.fuel > 0:
                self.fuel = self.fuel - BURNING_RATE
            # smoke step
            if ACTIVATE_SMOKE:
                self.smoke.smoke_step(self.burning)

    # Mesa framework native method, which is overwritten, necessary for executing changes made in step() method. This
    # logic is required to not update the overall grid state until all cells step() method where executed.
    def advance(self):
        # make fire spread slower
        if self.steps_counter % FIRE_SPREAD_SPEED == 0:
            # only state changes are logged: a message per cell per step would mean hundreds of thousands
            # of records for a default sized grid
            if self.next_burning_state and not self.burning:
                self.model.log.debug("cell %s ignited (p=%.3f, fuel=%d)", self.pos, self.cell_prob, self.fuel)
            elif self.burning and self.fuel <= 0:
                self.model.log.debug("cell %s burnt out", self.pos)
            self.burning = self.next_burning_state


# Class Smoke holds methods for managing smoke functionality
class Smoke:

    # constructor
    def __init__(self, fire_cell_fuel):
        self.smoke = False
        self.dispelling_counter_start_value = fire_cell_fuel
        self.dispelling_lower_bound_start_value = SMOKE_PRE_DISPELLING_COUNTER
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


# Class Wind holds methods for managing wind functionality
class Wind:

    # constructor
    def __init__(self):
        self.wind_direction = WIND_DIRECTION

    # it allows to change wind direction based on FIRST_DIR_PROB value
    def change_direction(self):
        if SYSTEM_RANDOM.random() < FIRST_DIR_PROB:
            self.wind_direction = FIRST_DIR
        else:
            self.wind_direction = SECOND_DIR

    # function to apply wind to partial burning probability of cell s (relative_center_pos),
    # caused by cell s' (adjacent_pos)
    def apply_wind(self, aux_prob, relative_center_pos, adjacent_pos):
        # if wind is compound by more than one direction
        if not FIXED_WIND:
            self.change_direction()
            # print("Wind: ", self.wind_direction)
        if self.is_on_wind_direction(relative_center_pos, adjacent_pos):
            aux_prob = aux_prob + (MU * (1 - aux_prob))  # part of 1 I- 'aux_prob' probability is added, depending on mu
        else:
            aux_prob = aux_prob - (MU * aux_prob)  # part of 'aux_prob' probability is removed, depending on mu
        return aux_prob

    # function that checks if cell located in relative_center_pos is on wind direction, influenced by cell located
    # in adjacent_pos
    def is_on_wind_direction(self, relative_center_pos, adjacent_pos):
        on_wind_direction = False
        if self.wind_direction == 'east':
            if (relative_center_pos[0] > adjacent_pos[0]) and (relative_center_pos[1] == adjacent_pos[1]):
                on_wind_direction = True
        elif self.wind_direction == 'west':
            if (relative_center_pos[0] < adjacent_pos[0]) and (relative_center_pos[1] == adjacent_pos[1]):
                on_wind_direction = True
        elif self.wind_direction == 'north':
            if (relative_center_pos[1] > adjacent_pos[1]) and (relative_center_pos[0] == adjacent_pos[0]):
                on_wind_direction = True
        elif self.wind_direction == 'south':
            if (relative_center_pos[1] < adjacent_pos[1]) and (relative_center_pos[0] == adjacent_pos[0]):
                on_wind_direction = True
        return on_wind_direction


# Class UAV holds methods for managing UAV agents
class UAV(mesa.Agent):

    # constructor
    def __init__(self, unique_id, model):
        super().__init__(unique_id, model)
        self.moore = True
        # the order for the next step, set by the model from what the policy returned: a direction, and how
        # many cells to cover along it. One cell is what a UAV flew before speeds existed.
        self.selected_dir = 0
        self.selected_speed = 1
        # firefighting extension: UAVs leave the base with a full load of water
        self.water = UAV_WATER_CAPACITY if ACTIVATE_FIREFIGHTING else 0

    # checks whether this UAV still carries water to dump | True if it does, False if it is empty
    def has_water(self):
        return self.water > 0

    # refills this UAV, which the home base does once a refill has taken BASE_REFILL_STEPS steps
    def refill(self):
        self.water = UAV_WATER_CAPACITY

    # dumps one load of water on the cell the UAV is over. The drop extinguishes cells within
    # WATER_DROP_RADIUS with a probability that falls off with distance from the centre of the drop.
    # Returns the number of burning cells actually put out.
    def dump_water(self):
        if not self.has_water():
            self.model.log.debug("UAV %d cannot dump, it is empty", self.unique_id)
            return 0

        self.water -= 1
        extinguished = 0
        affected_cells = self.model.grid.get_neighborhood(
            self.pos, moore=self.moore, include_center=True, radius=WATER_DROP_RADIUS
        )
        for cell in affected_cells:
            probability = extinguish_probability(self.pos, cell)
            if SYSTEM_RANDOM.random() >= probability:
                continue
            for agent in self.model.grid.get_cell_list_contents([cell]):
                if type(agent) is Fire and agent.extinguish():
                    extinguished += 1

        self.model.log.debug("UAV %d dumped water at %s, put out %d cell(s)",
                             self.unique_id, self.pos, extinguished)
        return extinguished

    # function that checks if an UAV in a certain position (pos), has another UAV nearby. If so, it can't move,
    # otherwise it will be possible to move.
    def not_UAV_adjacent(self, pos):
        can_move = True
        agents_in_pos = self.model.grid.get_cell_list_contents([pos])
        for agent in agents_in_pos:
            if type(agent) is UAV:
                can_move = False
        return can_move

    # function that obtains what this UAV can currently see, keeping the position of every observed cell.
    # surrounding_states() throws the positions away, which is enough to count burning cells but not enough
    # for a policy that has to decide which way to fly, so policies use this method instead.
    def observe(self):
        cells = []
        # obtains adjacent cells s' from a concrete cell s (self.pos)
        adjacent_cells = self.model.grid.get_neighborhood(
            self.pos, moore=self.moore, include_center=True, radius=UAV_OBSERVATION_RADIUS
        )
        # records (position, burning) for every observed cell that holds vegetation, and the positions of the
        # out buildings in view, which a policy may want to defend
        buildings = []
        for cell in adjacent_cells:
            for agent in self.model.grid.get_cell_list_contents([cell]):
                if type(agent) is Fire:
                    cells.append((cell, int(agent.is_burning() is True)))
                elif type(agent) is OutBuilding and not agent.destroyed:
                    buildings.append(cell)

        # the extension fields stay at their defaults when the extension is off, so that policies written
        # against the plain simulation keep working unchanged
        if not ACTIVATE_FIREFIGHTING:
            return Observation(uav_id=self.unique_id, pos=self.pos, cells=cells)

        return Observation(uav_id=self.unique_id, pos=self.pos, cells=cells,
                           has_water=self.has_water(),
                           base_pos=self.model.base.pos if self.model.base else None,
                           building_positions=buildings)

    # function for obtaining observed cells for the corresponding UAV
    def surrounding_states(self):
        # obtains each fire cell state, in a list (1 if its burning, 0 if it isn't)
        return self.observe().flat_states()

    # function for moving UAV over the grid area, up to selected_speed cells along selected_dir. Returns the
    # number of cells actually covered, which is less than the speed asked for when the UAV runs into the
    # edge of the grid or into another UAV.
    def move(self):
        # vectors for moving to different positions, based on 4 directions = [0, 1, 2, 3] = [right, down, left, up].
        # For example, if direction 1 is chosen, then the UAV moves 0 cells in x-axis, and -1 cell in y-axis
        move_x = [1, 0, -1, 0]
        move_y = [0, -1, 0, 1]
        previous_pos = self.pos

        # policies may hold position instead of moving; there is no movement vector for that
        if self.selected_dir == ACTION_STAY:
            self.model.log.debug("UAV %d holding position at %s", self.unique_id, self.pos)
            return 0

        # a UAV covers at most UAV_SPEED cells per step, whatever speed the policy asked for
        speed = max(0, min(int(self.selected_speed), UAV_SPEED))
        if speed == 0:
            self.model.log.debug("UAV %d ordered to move at zero speed, stayed at %s",
                                 self.unique_id, self.pos)
            return 0

        # the cells are crossed one at a time, so that the UAV stops at the edge of the grid or in front of
        # another UAV rather than jumping over it
        cells_moved = 0
        for _ in range(speed):
            pos_to_move = (self.pos[0] + move_x[self.selected_dir], self.pos[1] + move_y[self.selected_dir])
            # checks if the position to move is inside the grid bounds, and that the UAV doesn't have other UAV
            # nearby. If so, the UAV moves
            if self.model.grid.out_of_bounds(pos_to_move) or not self.not_UAV_adjacent(pos_to_move):
                break
            self.model.grid.move_agent(self, tuple(pos_to_move))
            cells_moved += 1

        # run scoped logger, set by the runner (see headless.py); silent when nothing configured it
        if cells_moved:
            self.model.log.debug("UAV %d moved %s -> %s (dir=%d, %d/%d cells)",
                                 self.unique_id, previous_pos, self.pos, self.selected_dir,
                                 cells_moved, speed)
        else:
            self.model.log.debug("UAV %d blocked, stayed at %s (dir=%d, speed=%d)",
                                 self.unique_id, self.pos, self.selected_dir, speed)

        return cells_moved

    # Mesa framework native method, which is overwritten, necessary for executing changes made in step() method
    # (as it can be seen, in this case UAVs don't need to update anything in step() method, so it isn't overwritten).
    def advance(self):
        # dumping water takes the whole step, so the UAV does not move as well
        if ACTIVATE_FIREFIGHTING and self.selected_dir == ACTION_DUMP_WATER:
            self.model.water_drops += 1
            self.model.cells_extinguished += self.dump_water()
            return

        self.move()

        # refilling is not an action: a UAV standing on the base with an empty tank starts refilling, and
        # the base itself decides whether it is free to serve it
        if ACTIVATE_FIREFIGHTING and self.model.base is not None:
            self.model.base.serve(self)


# Class Base holds the home base the UAVs start from and refill at. It is part of the firefighting
# extension, and is only placed on the grid when ACTIVATE_FIREFIGHTING is True.
class Base(mesa.Agent):

    # constructor. 'cells' is the footprint the base covers, its first entry being the anchor cell the
    # agent itself is placed on.
    def __init__(self, unique_id, model, cells=None):
        super().__init__(unique_id, model)
        self.cells = [tuple(cell) for cell in cells] if cells else []
        # damage taken so far, counted in steps during which any base cell was burning
        self.burning_steps = 0
        # unique_id of the UAV currently refilling, and how many steps it still has to wait. Only
        # BASE_CAPACITY UAVs can be served at a time, which the requirement sets to one.
        self.serving = {}

    # checks whether a position is part of the base footprint
    def covers(self, position):
        return tuple(position) in self.cells

    # checks whether any cell of the base is burning right now
    def is_burning(self):
        for cell in self.cells:
            for agent in self.model.grid.get_cell_list_contents([cell]):
                if type(agent) is Fire and agent.is_burning():
                    return True
        return False

    # checks whether the base has taken all the damage it can survive
    def is_destroyed(self):
        return self.burning_steps >= BHP

    # serves one UAV standing on the base cell, if there is a free refilling slot. A refill takes
    # BASE_REFILL_STEPS steps, during which the slot stays taken.
    def serve(self, uav):
        if not self.covers(uav.pos) or uav.has_water():
            # a UAV that leaves, or that is already full, gives its slot back
            self.serving.pop(uav.unique_id, None)
            return False

        if uav.unique_id not in self.serving:
            if len(self.serving) >= BASE_CAPACITY:  # somebody else is refilling
                self.model.log.debug("UAV %d is waiting for the base to be free", uav.unique_id)
                return False
            self.serving[uav.unique_id] = BASE_REFILL_STEPS
            self.model.log.debug("UAV %d started refilling at the base", uav.unique_id)

        self.serving[uav.unique_id] -= 1
        if self.serving[uav.unique_id] <= 0:
            uav.refill()
            self.model.refills += 1
            self.model.log.debug("UAV %d refilled at the base", uav.unique_id)
            # the slot is not released here: it stays taken until the next step, so that no more than
            # BASE_CAPACITY UAVs can be served within one simulation step
            return True
        return False

    # Mesa framework native method. The base accumulates damage while its cell burns, and frees the
    # refilling slots taken during the previous step.
    def step(self):
        if self.is_burning():
            self.burning_steps += 1
            self.model.log.info("home base is burning: %d/%d", self.burning_steps, BHP)

        for uav_id in list(self.serving):
            uav = self.model.uav_by_id(uav_id)
            # release the slot of a finished refill, and of a UAV that flew away mid refill, so that a
            # queued UAV is not blocked forever
            if self.serving[uav_id] <= 0 or uav is None or not self.covers(uav.pos):
                del self.serving[uav_id]


# Class BaseTile covers one cell of the home base footprint other than the anchor one. It carries no state
# of its own: it exists so that the whole footprint is drawn on the map, and the base it belongs to holds
# the damage and the refilling queue for all of its cells.
class BaseTile(mesa.Agent):

    # constructor
    def __init__(self, unique_id, model, base):
        super().__init__(unique_id, model)
        self.base = base


# Class OutBuilding holds the buildings scattered over the map that burn and are worth protecting. Part of
# the firefighting extension, only placed when ACTIVATE_FIREFIGHTING is True.
class OutBuilding(mesa.Agent):

    # constructor
    def __init__(self, unique_id, model):
        super().__init__(unique_id, model)
        self.burning_steps = 0
        self.destroyed = False

    # checks whether the cell this building stands on is burning
    def is_burning(self):
        for agent in self.model.grid.get_cell_list_contents([self.pos]):
            if type(agent) is Fire:
                return agent.is_burning()
        return False

    # Mesa framework native method. The building accumulates damage while its cell burns, and is lost once
    # it has burned for OUT_BUILDING_HP steps.
    def step(self):
        if self.destroyed or not self.is_burning():
            return

        self.burning_steps += 1
        if self.burning_steps >= OUT_BUILDING_HP:
            self.destroyed = True
            self.model.buildings_lost += 1
            self.model.log.info("out building at %s destroyed", self.pos)
