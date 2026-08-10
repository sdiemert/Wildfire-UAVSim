# python libraries

import mesa

# own python modules

import config

from sim import formulas
from sim.agents.fire import Fire
from sim.agents.out_building import OutBuilding
from sim.policy import Observation


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
        # positioning error extension: the fixed part of this UAV's positioning error, one integer offset
        # per axis, in cells. Drawn once here and held for the whole run, which is what a receiver that was
        # never calibrated looks like: this airframe is off by the same amount, in the same direction, all
        # run. (0, 0) with the extension switched off, and nothing is drawn for it then.
        self.position_bias = formulas.draw_position_offset(config.UAV_POSITION_BIAS_MAX)
        # positioning error extension: what identifies this UAV to formulas.position_noise(), which works
        # out the jitter of a fix from the UAV and the step rather than by drawing from SYSTEM_RANDOM. Drawn
        # here, so a run stays reproducible from one seed; see position_offset() for why the jitter itself is
        # kept out of the shared generator.
        self._noise_seed = config.SYSTEM_RANDOM.getrandbits(64) if config.ACTIVATE_POSITION_ERROR else 0
        # (step, offset) of the fix this UAV last worked out, memoised so that the arithmetic is done once
        # per step however many times it is asked for: WildFireModel.observations() asks every UAV what it
        # can see so the policy can decide, ModelSensor.uav_report() asks again on behalf of the managing
        # system, and the status panel asks a third time. All three have to be told the same thing, which
        # they are whether or not this cache is warm. What is cached is the offset and not the position it
        # produces, because the UAV moves during the step while the step number stays put.
        self._position_offset = (None, (0, 0))

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
    # from fuel_burn_cost() in sim/formulas.py, which the policies read as well. The tank is clamped at
    # zero, so an empty one lands exactly on 0.0 rather than drifting negative. Returns the fuel burned.
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

    # the offset between where this UAV is and where it believes it is, on the step being taken now: its
    # fixed bias plus the jitter of this step, in cells, per axis. Both are (0, 0) with the positioning
    # error extension switched off, which makes this method free and the measured position identical to the
    # true one.
    #
    # The jitter comes from formulas.position_noise(), which works it out from this UAV and the step number
    # instead of drawing from SYSTEM_RANDOM. So this method is free of side effects: the fix of a given UAV
    # on a given step is one fixed value, and asking for it -- once, twice, out of turn, for one UAV and not
    # its team mates, or from the web interface between steps -- cannot change the run. The cache below is
    # therefore a memo and nothing more, which is what lets the status panel show a UAV's fix beside its true
    # position without the act of watching a simulation altering it.
    def position_offset(self):
        # evaluation_timesteps_counter is an int for the whole life of a UAV, because reset() sets it before
        # the team is created. A UAV built against a bare model would leave it None, so -1 stands in for it:
        # no run ever reaches that step.
        step = self.model.evaluation_timesteps_counter
        step = -1 if step is None else int(step)

        known_for, offset = self._position_offset
        if known_for != step:
            noise = formulas.position_noise(self._noise_seed, step, config.UAV_POSITION_NOISE_MAX)
            offset = (self.position_bias[0] + noise[0], self.position_bias[1] + noise[1])
            self._position_offset = (step, offset)
            if offset[0] or offset[1]:
                self.model.log.debug("UAV %d fixes itself %s off its true cell %s at step %s",
                                     self.unique_id, offset, self.pos, step)

        return offset

    # where this UAV believes it is: its true cell displaced by the positioning error of this step, clamped
    # into the grid so that the answer is always a cell that exists. This is the position its policy plans
    # from, the position it reports to the team mates that can see it, and the position the managing system
    # is shown. Nothing in the simulation itself is ever driven by it: ground truth -- self.pos, the mesa
    # grid position -- is what the UAV flies from, what collisions and MR2 are settled from, what fuel is
    # charged against and what the home base serves, and this method never touches it.
    #
    # None for a UAV that has been destroyed, which has been taken off the grid and so has no position to
    # measure. Exactly self.pos with the extension switched off, so an Observation built for a run without
    # it is the object it always was.
    def measured_pos(self):
        if self.pos is None:
            return None

        offset_x, offset_y = self.position_offset()
        if not offset_x and not offset_y:
            return self.pos

        # the grid is built as MultiGrid(HEIGHT, WIDTH) for matrix accessing purposes, see the note in
        # WildFireModel.reset(), so x runs over grid.width and y over grid.height. Clamped rather than
        # wrapped or refused, because a receiver that is wrong does not stop answering, and every policy is
        # entitled to an Observation.pos that names a cell of the grid.
        return (min(max(self.pos[0] + offset_x, 0), self.model.grid.width - 1),
                min(max(self.pos[1] + offset_y, 0), self.model.grid.height - 1))

    # function that obtains what this UAV can currently see, keeping the position of every observed cell.
    # surrounding_states() throws the positions away, which is enough to count burning cells but not enough
    # for a policy that has to decide which way to fly, so policies use this method instead.
    #
    # With the positioning error extension on, 'pos' is what this UAV measured rather than where it is, and
    # the entries of 'uav_positions' are what the team mates in view measured about themselves, while
    # 'cells', 'base_pos', 'base_cells' and 'building_positions' stay in true grid coordinates. That
    # asymmetry is the whole extension: a policy steers by the difference between pos and its target, so
    # displacing the terrain by the same offset would cancel the error out and nothing would change. What is
    # corrupted is the receiver, not the camera. For the same reason the observed area below stays centred
    # on the true position: the camera really did see that ground, whatever the UAV believes about where it
    # was standing when it did.
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
                    # what the team mate itself measured, rather than the cell it is really standing on.
                    # There is no UAV to UAV link anywhere in this project, so "it told the team where it
                    # is" is modelled here, and the cell recorded is that UAV's own single self measurement:
                    # this UAV and the managing system are therefore told one and the same thing about it.
                    neighbours.append(agent.measured_pos())
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
            return Observation(uav_id=self.unique_id, pos=self.measured_pos(), cells=cells,
                               uav_positions=neighbours,
                               fuel=fuel, fuel_capacity=capacity)

        return Observation(uav_id=self.unique_id, pos=self.measured_pos(), cells=cells,
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

        # run scoped logger, set by the runner (see sim/cli/); silent when nothing configured it
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
