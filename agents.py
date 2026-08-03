# python libraries

import mesa
import functools

# own python modules

from sim.policy import Observation

# imported as a module rather than with 'from config import *', so that every setting is looked up when it
# is used. A star import copies the values into this module's namespace, which is why a runner overriding a
# constant (see headless.py) used to have to reach into every module that had copied it. Reading through
# 'config' leaves one copy to patch, the way the policy package has always done it.
import config

from sim import formulas


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


# Class Wind holds methods for managing wind functionality
class Wind:

    # constructor
    def __init__(self):
        self.wind_direction = config.WIND_DIRECTION

    # it allows to change wind direction based on FIRST_DIR_PROB value
    def change_direction(self):
        if config.SYSTEM_RANDOM.random() < config.FIRST_DIR_PROB:
            self.wind_direction = config.FIRST_DIR
        else:
            self.wind_direction = config.SECOND_DIR

    # function to apply wind to partial burning probability of cell s (relative_center_pos),
    # caused by cell s' (adjacent_pos)
    def apply_wind(self, aux_prob, relative_center_pos, adjacent_pos):
        # if wind is compound by more than one direction
        if not config.FIXED_WIND:
            self.change_direction()
            # print("Wind: ", self.wind_direction)
        if self.is_on_wind_direction(relative_center_pos, adjacent_pos):
            aux_prob = aux_prob + (config.MU * (1 - aux_prob))  # part of 1 I- 'aux_prob' probability is added, depending on mu
        else:
            aux_prob = aux_prob - (config.MU * aux_prob)  # part of 'aux_prob' probability is removed, depending on mu
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
        # health points. Sharing a cell with another UAV costs a rolled amount of them per step, and a UAV
        # that runs out is destroyed. WildFireModel.resolve_collisions() is what charges the damage,
        # because whether two UAVs share a cell is a property of the grid rather than of either of them.
        self.hp = config.UAV_HP
        # fuel extension: UAVs take off with a full tank. The attribute is set whether or not the
        # extension is on, so that the interface and the tests need no special case for it; what
        # ACTIVATE_FUEL governs is whether burn_fuel() ever takes anything off it.
        self.fuel = float(config.UAV_FUEL)
        # firefighting extension: UAVs leave the base with a full load of water
        self.water = config.UAV_WATER_CAPACITY if config.ACTIVATE_FIREFIGHTING else 0

    # checks whether this UAV is still flying | True until its health points run out
    def is_alive(self):
        return self.hp > 0

    # takes health points off this UAV, never below zero. Returns the points actually lost, so that a
    # caller can tell a hit that landed from one on a UAV that was already down.
    def take_damage(self, amount=1):
        if not self.is_alive():
            return 0
        lost = min(self.hp, max(0, int(amount)))
        self.hp -= lost
        self.model.log.debug("UAV %d took %d damage at %s, %d HP left",
                             self.unique_id, lost, self.pos, self.hp)
        return lost

    # rolls the damage of one collision and takes it off this UAV. The loss is a whole health point or
    # nothing at all, with UAV_COLLISION_DAMAGE_MEAN as its average, so health points stay whole numbers
    # while a collision can be made to cost less than a certain point. Returns the points lost, which is
    # zero for a roll that did no harm as well as for a UAV that was already down.
    def take_collision_damage(self):
        return self.take_damage(formulas.roll_collision_damage())

    # checks whether this UAV has run dry | always False when the fuel extension is switched off, so that
    # nothing downstream has to test the flag itself. WildFireModel.resolve_fuel() is what acts on it.
    def is_out_of_fuel(self):
        return config.ACTIVATE_FUEL and self.fuel <= 0

    # checks whether the tank is full, which is what tells the base there is nothing to refuel
    def has_full_tank(self):
        return self.fuel >= config.UAV_FUEL

    # burns the fuel one step of flight cost this UAV, given the cells it actually covered. The cost comes
    # from fuel_burn_cost() in config.py, which the policies read as well. The tank is clamped at zero, so
    # an empty one lands exactly on 0.0 rather than drifting negative. Returns the fuel actually burned.
    def burn_fuel(self, cells_moved):
        if not config.ACTIVATE_FUEL:
            return 0.0

        burned = min(self.fuel, formulas.fuel_burn_cost(cells_moved, at_base=self.model.at_base(self.pos)))
        self.fuel -= burned
        self.model.log.debug("UAV %d burned %.2f fuel over %d cell(s), %.2f left",
                             self.unique_id, burned, cells_moved, self.fuel)
        return burned

    # fills the tank, which the home base does once a refuel has taken BASE_REFUEL_STEPS steps
    def refuel(self):
        self.fuel = float(config.UAV_FUEL)

    # checks whether this UAV still carries water to dump | True if it does, False if it is empty
    def has_water(self):
        return self.water > 0

    # refills this UAV, which the home base does once a refill has taken BASE_REFILL_STEPS steps
    def refill(self):
        self.water = config.UAV_WATER_CAPACITY

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
            self.pos, moore=self.moore, include_center=True, radius=config.WATER_DROP_RADIUS
        )
        for cell in affected_cells:
            probability = formulas.extinguish_probability(self.pos, cell)
            if config.SYSTEM_RANDOM.random() >= probability:
                continue
            for agent in self.model.grid.get_cell_list_contents([cell]):
                if type(agent) is Fire and agent.extinguish():
                    extinguished += 1

        self.model.log.debug("UAV %d dumped water at %s, put out %d cell(s)",
                             self.unique_id, self.pos, extinguished)
        return extinguished

    # function that lists the other UAVs still flying on a given cell. An empty list means the cell is
    # clear of traffic; anything else means moving there is a collision.
    def other_uavs_at(self, pos):
        return [agent for agent in self.model.grid.get_cell_list_contents([pos])
                if type(agent) is UAV and agent is not self and agent.is_alive()]

    # function that obtains what this UAV can currently see, keeping the position of every observed cell.
    # surrounding_states() throws the positions away, which is enough to count burning cells but not enough
    # for a policy that has to decide which way to fly, so policies use this method instead.
    def observe(self):
        cells = []
        # obtains adjacent cells s' from a concrete cell s (self.pos)
        adjacent_cells = self.model.grid.get_neighborhood(
            self.pos, moore=self.moore, include_center=True, radius=config.UAV_OBSERVATION_RADIUS
        )
        # records (position, burning) for every observed cell that holds vegetation, the cells the other
        # UAVs in view are standing on, which a policy needs to keep clear of, and the positions of the out
        # buildings in view, which a policy may want to defend
        buildings = []
        neighbours = []
        for cell in adjacent_cells:
            for agent in self.model.grid.get_cell_list_contents([cell]):
                if type(agent) is Fire:
                    cells.append((cell, int(agent.is_burning() is True)))
                elif type(agent) is UAV and agent is not self and agent.is_alive():
                    neighbours.append(cell)
                elif type(agent) is OutBuilding and not agent.destroyed:
                    buildings.append(cell)

        # the fuel a policy is told about. Left at None when the extension is off, so that a policy can
        # tell "the tank is empty" apart from "fuel is not being tracked in this run" and ignore it
        # entirely; Observation.low_fuel() reports False either way.
        fuel = self.fuel if config.ACTIVATE_FUEL else None
        capacity = float(config.UAV_FUEL) if config.ACTIVATE_FUEL else None

        # the extension fields stay at their defaults when the extension is off, so that policies written
        # against the plain simulation keep working unchanged. The UAVs in view are reported either way,
        # because collisions do not belong to the extension, and so is the fuel, which has a switch of its
        # own and is burned with or without the firefighting extension.
        if not config.ACTIVATE_FIREFIGHTING:
            return Observation(uav_id=self.unique_id, pos=self.pos, cells=cells,
                               uav_positions=neighbours,
                               fuel=fuel, fuel_capacity=capacity)

        return Observation(uav_id=self.unique_id, pos=self.pos, cells=cells,
                           uav_positions=neighbours,
                           fuel=fuel, fuel_capacity=capacity,
                           has_water=self.has_water(),
                           base_pos=self.model.base.pos if self.model.base else None,
                           base_cells=list(self.model.base.cells) if self.model.base else [],
                           building_positions=buildings)

    # function for obtaining observed cells for the corresponding UAV
    def surrounding_states(self):
        # obtains each fire cell state, in a list (1 if its burning, 0 if it isn't)
        return self.observe().flat_states()

    # function for moving UAV over the grid area, up to selected_speed cells along selected_dir. Returns the
    # number of cells actually covered, which is less than the speed asked for when the UAV runs into the
    # edge of the grid, or into another UAV: it flies onto the cell the other one holds and stops there,
    # having collided with it. WildFireModel.resolve_collisions() charges both of them for it at the end of
    # the step.
    def move(self):
        # vector for moving to a different position, one per direction = [right, down, left, up]. For
        # example, if direction 1 is chosen, then the UAV moves 0 cells in x-axis, and -1 cell in y-axis.
        # The table lives in config.py, because the policies read it to predict where an action lands.
        previous_pos = self.pos

        # policies may hold position instead of moving; there is no movement vector for that
        if self.selected_dir == config.ACTION_STAY:
            self.model.log.debug("UAV %d holding position at %s", self.unique_id, self.pos)
            return 0

        # a UAV covers at most UAV_SPEED cells per step, whatever speed the policy asked for
        speed = max(0, min(int(self.selected_speed), config.UAV_SPEED))
        if speed == 0:
            self.model.log.debug("UAV %d ordered to move at zero speed, stayed at %s",
                                 self.unique_id, self.pos)
            return 0

        # the cells are crossed one at a time, so that the UAV stops at the edge of the grid, and so that it
        # cannot jump over an occupied cell without having been in it
        move_x, move_y = config.MOVEMENT_VECTORS[self.selected_dir]
        cells_moved = 0
        for _ in range(speed):
            pos_to_move = (self.pos[0] + move_x, self.pos[1] + move_y)
            # checks if the position to move is inside the grid bounds. If so, the UAV moves
            if self.model.grid.out_of_bounds(pos_to_move):
                break
            # flying onto a cell another UAV holds is a collision, and the flight ends there. The home base
            # is shared airspace, so traffic over its footprint neither collides nor stops.
            blocked = bool(self.other_uavs_at(pos_to_move)) and not self.model.at_base(pos_to_move)
            self.model.grid.move_agent(self, tuple(pos_to_move))
            cells_moved += 1
            if blocked:
                break

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
        # a destroyed UAV is taken off the grid and out of the scheduler, so this is only reached by one
        # that is still flying. Checked anyway, because a caller may step a UAV directly.
        if not self.is_alive():
            return

        # dumping water takes the whole step, so the UAV does not move as well
        cells_moved = 0
        if config.ACTIVATE_FIREFIGHTING and self.selected_dir == config.ACTION_DUMP_WATER:
            self.model.water_drops += 1
            self.model.cells_extinguished += self.dump_water()
        else:
            cells_moved = self.move()

            # refilling is not an action: a UAV standing on the base with an empty tank or a part empty
            # fuel tank starts being served, and the base itself decides whether it is free to serve it
            if config.ACTIVATE_FIREFIGHTING and self.model.base is not None:
                self.model.base.serve(self)

        # the step is paid for last, from the distance actually covered, so that a UAV stopped early by the
        # grid edge or by another UAV is not charged for the flight it did not make. Running the tank dry
        # does not kill the UAV here: WildFireModel.resolve_fuel() settles that once the whole schedule has
        # run, because destroying an agent mid schedule would mutate what the scheduler is iterating over.
        self.burn_fuel(cells_moved)


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
        return self.burning_steps >= config.BHP

    # checks whether a UAV standing on the base wants anything from it: water, or fuel when the fuel
    # extension is on. With ACTIVATE_FUEL off this is exactly the empty tank test it has always been.
    def needs_service(self, uav):
        return not uav.has_water() or (config.ACTIVATE_FUEL and not uav.has_full_tank())

    # how long one visit to the base takes. Water and fuel are taken on together in a single visit, so a
    # UAV that wants both waits for the slower of the two rather than queueing twice.
    def service_steps(self):
        return max(config.BASE_REFILL_STEPS, config.BASE_REFUEL_STEPS) if config.ACTIVATE_FUEL else config.BASE_REFILL_STEPS

    # serves one UAV standing on the base cell, if there is a free slot. A visit takes service_steps()
    # steps, during which the slot stays taken, and hands over a full load of water and a full tank.
    def serve(self, uav):
        if not self.covers(uav.pos) or not self.needs_service(uav):
            # a UAV that leaves, or that wants nothing, gives its slot back
            self.serving.pop(uav.unique_id, None)
            return False

        if uav.unique_id not in self.serving:
            if len(self.serving) >= config.BASE_CAPACITY:  # somebody else is being served
                self.model.log.debug("UAV %d is waiting for the base to be free", uav.unique_id)
                return False
            self.serving[uav.unique_id] = self.service_steps()
            self.model.log.debug("UAV %d started refilling at the base", uav.unique_id)

        self.serving[uav.unique_id] -= 1
        if self.serving[uav.unique_id] <= 0:
            uav.refill()
            if config.ACTIVATE_FUEL:
                uav.refuel()
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
            self.model.log.info("home base is burning: %d/%d", self.burning_steps, config.BHP)

        for uav_id in list(self.serving):
            uav = self.model.uav_by_id(uav_id)
            # release the slot of a finished refill, and of a UAV that flew away mid refill or was
            # destroyed on the base, so that a queued UAV is not blocked forever
            if self.serving[uav_id] <= 0 or uav is None or not uav.is_alive() or not self.covers(uav.pos):
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
        if self.burning_steps >= config.OUT_BUILDING_HP:
            self.destroyed = True
            self.model.buildings_lost += 1
            self.model.log.info("out building at %s destroyed", self.pos)
