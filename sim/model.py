# python libraries

import itertools
import logging
import mesa
import numpy

# own python modules

import config

from sim import agents, environment, fire_spread, formulas, smoke

# imported by name because 'policy' is also the name of the constructor argument and attribute below,
# which would shadow the module
from sim.policy import Action, RandomPolicy, build_policy


# class WildFireModel holds methods for managing the main logic of the grid, such as the main execution loop,
# setting agents, methods for checking the state of the grid, etc
class WildFireModel(mesa.Model):

    # constructor. 'log' lets a runner (see sim/cli/) hand in a run specific logger, so that agent messages
    # are attributed to the simulation they came from. When it isn't given, messages go to the shared
    # "wildfire.model" logger, which has no handlers unless something configured it, and so stays silent.
    def __init__(self, log=None, policy=None):

        # the bounds documented in config.py are checked here, before anything is built, so that an out of
        # bounds setting is reported against its own name rather than surfacing as a ZeroDivisionError or
        # a KeyError somewhere deep in a step
        config.validate()

        # set before reset(), because agents log through self.model.log while they are being created
        self.log = log if log is not None else logging.getLogger("wildfire.model")

        # the policy that chooses UAV directions each step. Defaults to the original uniform random choice,
        # so any existing caller behaves exactly as before. A policy name is accepted as well as an instance,
        # because the web interface dropdown hands its selection over as a string.
        if policy is None:
            policy = RandomPolicy()
        elif isinstance(policy, str):
            policy = build_policy(policy)
        self.policy = policy

        # attributes intialization

        self.new_direction_counter = None
        self.datacollector = None
        self.grid = None
        self.unique_agents_id = None
        self.new_direction = None
        self.evaluation_timesteps_counter = None
        self.NUM_AGENTS = config.NUM_AGENTS

        # the monitoring scores themselves are set up by reset(), so that restarting a run in place clears
        # them rather than carrying the previous run's totals forward
        self.MR1_LIST = []
        self.MR2_VALUE = 0

        self.reset()

        # makes the active policy visible on the console when the web interface Reset button reinstantiates
        # the model, which is otherwise silent about which selection took effect
        self.log.info("model ready: %d UAVs, policy=%s", self.NUM_AGENTS, self.policy)

    # reset method with attributes initialization. This method should be used whenever it is needed to reset the
    # environment in execution time. For example, when the graphical interface is up, and reset button is pressed, this
    # method is called
    def reset(self):

        # Mesa's visualization server stops asking for steps once this turns False, and sets it back to True
        # itself when the model is reinstantiated by the Reset button
        self.running = True

        # the monitoring metrics belong to one run, so they start again from nothing here. MR1_LIST is
        # indexed by place in the team, which is why it is sized from the team rather than appended to.
        self.MR1_LIST = [0.0 for _ in range(0, self.NUM_AGENTS)]
        self.MR2_VALUE = 0

        self.unique_agents_id = 0
        # Inverted width and height order, because of matrix accessing purposes, like in many examples:
        #   https://snyk.io/advisor/python/Mesa/functions/mesa.space.MultiGrid
        # set some Mesa framework management
        self.grid = mesa.space.MultiGrid(config.HEIGHT, config.WIDTH, False)
        self.schedule = mesa.time.SimultaneousActivation(self)
        # where and when the wildfire starts. Both are resolved once per run, before the Fire agents are
        # created, because the ignition cell has to exist whatever the tree density decides
        self.fire_start_pos = self.resolve_fire_start_position()
        self.fire_start_step = self.resolve_fire_start_step()
        self.fire_started = False
        # the Fire agents, in creation order, and their positions split into index arrays. Together
        # they turn the burning state of the whole grid into a single array assignment each step,
        # which is what feeds the vectorized spread calculation below. Set up before
        # set_fire_agents(), because new_fire_agent() appends to them.
        self.fire_list = []
        self.fire_xs = []
        self.fire_ys = []
        # burning mask and ignition probabilities of the whole grid, indexed [x, y] to match the
        # Mesa grid positions, whose x runs over HEIGHT (see the MultiGrid call above)
        self.burning = numpy.zeros((config.HEIGHT, config.WIDTH), dtype=bool)
        self.fire_prob = numpy.zeros((config.HEIGHT, config.WIDTH))
        # which cells are raising smoke, and which are covered by the plumes that smoke blows into. Same
        # indexing as the two above. The plume field is only built when smoke actually blinds somebody:
        # with the extension off nothing is ever opaque, occluded() answers False without a lookup, and the
        # convolution below is never run at all
        self.smoking = numpy.zeros((config.HEIGHT, config.WIDTH), dtype=bool)
        self.smoke_opaque = numpy.zeros((config.HEIGHT, config.WIDTH), dtype=bool)
        # rebuilt per reset, so that a runner overriding the wind settings is picked up
        self.fire_spread = fire_spread.FireSpread(config.HEIGHT, config.WIDTH)
        self.smoke_field = (smoke.SmokeField(config.HEIGHT, config.WIDTH)
                            if config.ACTIVATE_SMOKE and config.SMOKE_OCCLUDES_OBSERVATION else None)
        # set Fire and wind agents (Smoke are created inside Fire agents as well)
        self.set_fire_agents()
        self.fire_xs = numpy.array(self.fire_xs, dtype=int)
        self.fire_ys = numpy.array(self.fire_ys, dtype=int)
        self.fire_spread.assert_matches(self.fire_list)
        self.wind = environment.Wind()

        self.new_direction_counter = 0
        self.evaluation_timesteps_counter = 0

        # firefighting extension: place the home base and the out buildings before the UAVs, because the
        # UAVs start from the base
        self.base = None
        self.out_buildings = []
        self.water_drops = 0
        self.cells_extinguished = 0
        self.refills = 0
        self.buildings_lost = 0
        self.lost = False
        # UAV collisions: how many times a cell was found holding more than one UAV, and how many UAVs
        # that cost the team. Counted whether or not the firefighting extension is on.
        self.collisions = 0
        self.uavs_lost = 0
        # of the UAVs lost above, how many ran their tanks dry rather than being destroyed in a collision
        self.uavs_out_of_fuel = 0
        if config.ACTIVATE_FIREFIGHTING:
            self.set_base()
            self.set_out_buildings()

        # the UAV team, in the order it was created. The scheduler holds one entry per cell of the
        # forest as well, so picking the UAVs back out of it means walking thousands of Fire agents
        # to find a handful; everything that needs the team iterates this list instead. The order is
        # the order they are added to the scheduler, which is what observations() and
        # set_drone_dirs() rely on to line actions up with the UAVs they belong to.
        self.uavs = []

        # create and configure UAV agents in the grid. A cell each, resolved in one go, so that no two
        # UAVs are launched stacked however large the team is
        launch_positions = self.launch_positions(self.NUM_AGENTS)

        for a in range(0, self.NUM_AGENTS):
            aux_UAV = agents.UAV(self.unique_agents_id, self)
            self.grid.place_agent(aux_UAV, launch_positions[a])
            self.schedule.add(aux_UAV)
            self.uavs.append(aux_UAV)
            self.unique_agents_id += 1

        # unique id -> place in the team, which is the index MR1_LIST is kept by. Built once here rather
        # than scanning self.uavs for each UAV on every step of every run.
        self.team_slot = {uav.unique_id: slot for slot, uav in enumerate(self.uavs)}

        # set Mesa framework management
        self.datacollector = mesa.DataCollector()
        self.new_direction = [0 for a in range(0, self.NUM_AGENTS)]

    # function that gives the cells the home base covers, at BASE_POSITION or a quarter into the grid by
    # default, as a BASE_SIZE footprint anchored on that position and clipped to the grid. It depends on
    # nothing but the configuration and the grid size, so that it can be consulted before the base agent
    # exists: a random ignition cell has to know which cells the base will occupy.
    def base_footprint(self):
        if not config.ACTIVATE_FIREFIGHTING:
            return []

        anchor = tuple(config.BASE_POSITION if config.BASE_POSITION is not None else (int(config.HEIGHT / 4), int(config.WIDTH / 4)))
        if self.grid.out_of_bounds(anchor):
            raise ValueError(f"BASE_POSITION {anchor} is outside the {config.HEIGHT}x{config.WIDTH} grid")

        # the anchor comes first, so that it stays the cell the Base agent itself sits on
        footprint = [anchor]
        for dx in range(config.BASE_SIZE[0]):
            for dy in range(config.BASE_SIZE[1]):
                cell = (anchor[0] + dx, anchor[1] + dy)
                if cell != anchor and not self.grid.out_of_bounds(cell):
                    footprint.append(cell)
        return footprint

    # function that places the home base over its footprint
    def set_base(self):
        footprint = self.base_footprint()
        anchor = footprint[0]

        self.base = agents.Base(self.unique_agents_id, self, cells=footprint)
        self.unique_agents_id += 1
        self.schedule.add(self.base)
        self.grid.place_agent(self.base, anchor)

        # the remaining cells of the footprint only need to be drawn, so they get a tile each
        for cell in footprint[1:]:
            tile = agents.BaseTile(self.unique_agents_id, self, self.base)
            self.unique_agents_id += 1
            self.grid.place_agent(tile, cell)

        self.log.info("home base placed at %s covering %d cell(s), surviving %d burning steps",
                      anchor, len(footprint), config.BHP)

    # function that gives the cell each UAV of the team starts the run from, in team order and one distinct
    # cell each, so that nobody is launched stacked. The home base footprint is handed out first, in the
    # order base_footprint() lists it, so that UAV 0 keeps the anchor; a team that outnumbers the footprint
    # spills over into the cells around the base, nearest ones first, taken at random within each ring so
    # that the overflow is not always laid out the same way. With the firefighting extension off there is no
    # base, and the centre of the grid stands in for it as the cell the team gathers round.
    def launch_positions(self, count):
        if count <= 0:
            return []

        home = list(self.base.cells) if self.base is not None else [(int(config.HEIGHT / 2), int(config.WIDTH / 2))]
        positions = home[:count]

        # the box the rings grow out of. Both the base footprint and the lone centre cell are rectangles,
        # so their bounding box is exactly the set of cells already handed out above
        box = (min(x for x, _ in home), min(y for _, y in home),
               max(x for x, _ in home), max(y for _, y in home))

        distance = 1
        while len(positions) < count:
            ring = self.launch_ring(box, distance)
            # a ring falling entirely outside the grid means the whole map has been handed out already
            if not ring:
                raise ValueError(f"{count} UAVs do not fit on the {config.HEIGHT}x{config.WIDTH} grid: "
                                 f"lower NUM_AGENTS or enlarge the grid")
            config.SYSTEM_RANDOM.shuffle(ring)
            positions.extend(ring[:count - len(positions)])
            distance += 1

        return positions

    # the cells exactly 'distance' cells away from the (x0, y0, x1, y1) box, that is the border of the box
    # grown by 'distance', clipped to the grid. Distance is counted the way the UAVs fly, diagonals
    # included, so the rings are square.
    def launch_ring(self, box, distance):
        x0, y0, x1, y1 = box
        ring = []
        for x in range(x0 - distance, x1 + distance + 1):
            for y in range(y0 - distance, y1 + distance + 1):
                on_border = x in (x0 - distance, x1 + distance) or y in (y0 - distance, y1 + distance)
                if on_border and not self.grid.out_of_bounds((x, y)):
                    ring.append((x, y))
        return ring

    # function that scatters the out buildings randomly over the grid, avoiding the base cell and any cell
    # that already holds a building
    def set_out_buildings(self):
        taken = set(self.base.cells) if self.base is not None else set()
        candidates = [(x, y) for x in range(config.HEIGHT) for y in range(config.WIDTH) if (x, y) not in taken]
        # more buildings than free cells cannot be placed; ask for what fits
        wanted = min(config.NUM_OUT_BUILDINGS, len(candidates))
        for position in config.SYSTEM_RANDOM.sample(candidates, wanted):
            building = agents.OutBuilding(self.unique_agents_id, self)
            self.unique_agents_id += 1
            self.schedule.add(building)
            self.grid.place_agent(building, position)
            self.out_buildings.append(building)
        if wanted:
            self.log.info("%d out building(s) placed at %s", wanted,
                          [building.pos for building in self.out_buildings])

    # looks a UAV up by its unique id, used by the base to check who is still standing on it. Destroyed
    # UAVs are found as well, so that a caller can tell one apart from an id that never existed.
    def uav_by_id(self, uav_id):
        for uav in self.uavs:
            if uav.unique_id == uav_id:
                return uav
        return None

    # the UAVs still flying, in team order. self.uavs keeps the whole team for the run, destroyed ones
    # included, because the sidebar reports what became of each of them and MR1_LIST is indexed by team
    # position; everything that acts on the fleet works from this list instead.
    def active_uavs(self):
        return [uav for uav in self.uavs if uav.is_alive()]

    # checks whether a position is part of the home base footprint. UAVs neither collide nor stop over the
    # base, which is what lets the whole team start from it and queue on it to refill.
    def at_base(self, position):
        return self.base is not None and self.base.covers(position)

    # function that decides which cell the wildfire starts from, from FIRE_START_POSITION
    def resolve_fire_start_position(self):
        setting = config.FIRE_START_POSITION

        if setting is None:  # the centre of the grid
            return int(config.HEIGHT / 2), int(config.WIDTH / 2)

        if isinstance(setting, str):
            if setting.lower() != "random":
                raise ValueError("FIRE_START_POSITION must be None, 'random' or an (x, y) cell, "
                                 f"got {setting!r}")
            # the home base is left out of the draw: a fire lit on top of it would have the base alight
            # from the first step, and BHP would run out before the UAVs could do anything about it
            reserved = set(self.base_footprint())
            candidates = [(x, y) for x in range(config.HEIGHT) for y in range(config.WIDTH) if (x, y) not in reserved]
            if not candidates:
                raise ValueError("no cell is free of the home base to start the fire from")
            return config.SYSTEM_RANDOM.choice(candidates)

        cell = tuple(setting)
        if self.grid.out_of_bounds(cell):
            raise ValueError(f"FIRE_START_POSITION {cell} is outside the {config.HEIGHT}x{config.WIDTH} grid")
        return cell

    # function that decides which step the wildfire starts at, from FIRE_START_STEP
    def resolve_fire_start_step(self):
        setting = config.FIRE_START_STEP

        # anywhere in the run. BATCH_SIZE is how long a run lasts, so the fire always keeps at least one
        # step to spread in
        if setting is None or (isinstance(setting, str) and setting.lower() == "random"):
            return config.SYSTEM_RANDOM.randrange(max(1, config.BATCH_SIZE))

        if isinstance(setting, (tuple, list)):  # a random step inside a range the user gave
            if len(setting) != 2:
                raise ValueError(f"FIRE_START_STEP range must be (first, last), got {setting!r}")
            first, last = max(0, int(setting[0])), max(0, int(setting[1]))
            if first > last:
                raise ValueError(f"FIRE_START_STEP range {setting!r} ends before it starts")
            return config.SYSTEM_RANDOM.randint(first, last)

        if isinstance(setting, str):
            raise ValueError("FIRE_START_STEP must be a step, a (first, last) range or 'random', "
                             f"got {setting!r}")

        return max(0, int(setting))  # one exact step

    # function that creates all fire agents in a grid
    def set_fire_agents(self):
        for i in range(config.HEIGHT):
            for j in range(config.WIDTH):
                # decides to put a "tree" (fire agent) or not, if less than DENSITY_PROB. The ignition cell
                # always gets one, whatever the density decides, because the fire has to start somewhere
                ignition_cell = (i, j) == self.fire_start_pos
                if config.SYSTEM_RANDOM.random() < config.DENSITY_PROB or ignition_cell:
                    # the ignition cell is created already burning when the fire starts at step 0, otherwise
                    # every cell starts unburnt and start_fire() lights it once the run reaches that step
                    self.new_fire_agent(i, j, ignition_cell and self.fire_start_step <= 0)

        if self.fire_start_step <= 0:
            self.fire_started = True
            self.log.info("fire lit at %s at the start of the run", self.fire_start_pos)
        else:
            self.log.info("fire will start at %s at step %d", self.fire_start_pos, self.fire_start_step)
            if self.fire_start_step >= config.BATCH_SIZE:
                self.log.warning("FIRE_START_STEP %d is not reached in a %d step run: nothing will burn",
                                 self.fire_start_step, config.BATCH_SIZE)

    # function that lights the initial wildfire on the resolved ignition cell. A delayed ignition is the
    # same event as a step 0 one: the cell starts burning, and the cells around it see it while they take
    # the step it was lit in, because every agent steps before any of them advances.
    def start_fire(self):
        self.fire_started = True
        cell = self.fire_agent_at(self.fire_start_pos)
        if cell is None:  # defensive: set_fire_agents() always creates the ignition cell
            self.log.error("no Fire agent at %s, the fire cannot start", self.fire_start_pos)
            return
        cell.burning = True
        self.log.info("fire started at %s at step %d (fuel=%d)",
                      self.fire_start_pos, self.evaluation_timesteps_counter, cell.get_fuel())

    # refreshes the burning mask from the Fire agents and works out the ignition probability of every
    # cell in one convolution (see sim/fire_spread.py). Fire.step() then reads its own cell out of
    # self.fire_prob instead of walking its neighbourhood, which is what the per cell version spent
    # over 99% of the run time doing.
    def update_fire_probabilities(self):
        if not self.fire_list:  # a density low enough to leave the grid bare
            return
        self.burning[self.fire_xs, self.fire_ys] = [fire.burning for fire in self.fire_list]
        self.fire_prob = self.fire_spread.probability_field(self.burning)

    # refreshes the mask of cells raising smoke from the Smoke each Fire owns, and blows it downwind into
    # the plume field that decides what can be observed (see sim/smoke.py). Built once per step and read
    # many times: observe() runs at least twice per UAV per step -- once for the policy, once for the
    # managing system's sensor -- and both have to be told the same thing about what the smoke hid.
    def update_smoke(self):
        if self.smoke_field is None or not self.fire_list:  # extension off, or a bare grid
            return
        self.smoking[self.fire_xs, self.fire_ys] = [fire.smoke.is_smoke_active() for fire in self.fire_list]
        self.smoke_opaque = self.smoke_field.opaque(self.smoking)

    # whether a cell is buried in smoke, and so cannot be observed at all. The single question every
    # observer asks, so that no caller indexes the mask itself and the extension being off costs one
    # attribute lookup rather than a rebuilt array of False.
    def occluded(self, position):
        if self.smoke_field is None:
            return False
        return bool(self.smoke_opaque[position[0], position[1]])

    # looks up the Fire agent covering a cell, or None when the density left that cell empty
    def fire_agent_at(self, position):
        for agent in self.grid.get_cell_list_contents([position]):
            if type(agent) is agents.Fire:
                return agent
        return None

    # function that creates new fire agent in a concrete cell
    def new_fire_agent(self, pos_x, pos_y, burning):
        # creates new Fire agent
        source_fire = agents.Fire(self.unique_agents_id, self, burning)
        # set Fire agent unique id, incremented from the one used before it
        self.unique_agents_id += 1
        # add to scheduler
        self.schedule.add(source_fire)
        # place agent in the grid
        self.grid.place_agent(source_fire, tuple([pos_x, pos_y]))
        # remember it for the vectorized spread calculation, which reads the burning state of every
        # Fire agent once per step through these parallel lists
        self.fire_list.append(source_fire)
        self.fire_xs.append(pos_x)
        self.fire_ys.append(pos_y)

    # manage actions obtained from the new_direction attribute, and make the UAV team move over the forest area
    def set_drone_dirs(self):
        # used for selecting the corresponding action from new_direction attribute, for each UAV
        self.new_direction_counter = 0
        # walks the UAVs still flying in the same order observations() reported them, so that entry i of
        # what the policy returned belongs to UAV i. What the policy returned is coerced into an Action, so
        # a policy that only gives a direction still works.
        for uav in self.active_uavs():
            action = Action.coerce(self.new_direction[self.new_direction_counter])
            uav.selected_dir = action.direction
            uav.selected_speed = action.speed
            self.new_direction_counter += 1

    # this method obtains effective wildfire monitoring metric (MR1) for time step t. 'flying' is the UAV
    # team the state was collected from, which is what says where in MR1_LIST each score belongs: a UAV
    # that has been destroyed stops scoring but keeps the total it earned while it flew.
    def MR1(self, state, flying=None):
        flying = self.active_uavs() if flying is None else flying
        for uav, aux_state in zip(flying, state):
            # normalized reward amount for this UAV state, added to the score of its place in the team.
            # self.team_slot maps the UAV to that place directly, rather than scanning the team for it
            reward = formulas.normalize(float(sum(aux_state)), config.N_OBSERVATIONS, 1, 0)
            self.MR1_LIST[self.team_slot[uav.unique_id]] += reward

    # this method obtains collision risk avoidance metric (MR2) for time step t. It counts the pairs of
    # UAVs flying closer to each other than SECURITY_DISTANCE, which is a measure of the collision risk a
    # policy accepts rather than a count of the collisions it caused: a collision is two UAVs sharing one
    # cell, and resolve_collisions() below is what charges for those.
    def MR2(self):
        # each unordered pair of UAVs still flying, visited once, so there is nothing to halve afterwards.
        # The distance is compared squared, which saves a square root per pair and is the same comparison.
        limit_squared = config.SECURITY_DISTANCE ** 2
        for one, other in itertools.combinations(self.active_uavs(), 2):
            gap_squared = (one.pos[0] - other.pos[0]) ** 2 + (one.pos[1] - other.pos[1]) ** 2
            if gap_squared < limit_squared:
                self.MR2_VALUE += 1

    # method that settles the collisions of the step just taken. Two or more UAVs left on the same cell
    # have collided, and each of them rolls for damage: a whole health point or nothing at all, averaging
    # out at UAV_COLLISION_DAMAGE_MEAN. One whose health points run out is destroyed. The home base is left
    # out, because any number of UAVs may sit on its footprint.
    #
    # self.collisions counts the collisions themselves rather than the damage they did, so a run with a low
    # UAV_COLLISION_DAMAGE_MEAN still reports how often the team flew into itself.
    #
    # It is settled once per step, from where the UAVs ended up, rather than while they fly: that way the
    # damage does not depend on the order the scheduler happened to move them in, and two UAVs left stacked
    # on one cell keep paying for it every step until they separate or are destroyed.
    def resolve_collisions(self):
        crowded = {}
        for uav in self.active_uavs():
            if self.at_base(uav.pos):
                continue
            crowded.setdefault(uav.pos, []).append(uav)

        for position, crowd in crowded.items():
            if len(crowd) < 2:
                continue
            self.collisions += 1
            damage = {uav.unique_id: uav.take_collision_damage() for uav in crowd}
            self.log.info("collision at %s between UAVs %s, health points lost: %s",
                          position, [uav.unique_id for uav in crowd], damage)
            for uav in crowd:
                if not uav.is_alive():
                    self.destroy_uav(uav, reason="collision")

    # method that settles the UAVs that ran their tanks dry during the step just taken. An empty tank
    # costs a UAV every health point it has left, so it is destroyed exactly as a fatal collision destroys
    # it, and for the same reason it is settled here rather than inside UAV.advance(): destroying an agent
    # takes it out of the scheduler, which must not happen while the scheduler is iterating.
    #
    # Run after resolve_collisions(), so a UAV that was destroyed by a collision on the same step is
    # already out of active_uavs() and is counted once, against the collision that actually killed it.
    def resolve_fuel(self):
        if not config.ACTIVATE_FUEL:
            return

        for uav in self.active_uavs():
            if not uav.is_out_of_fuel():
                continue
            self.uavs_out_of_fuel += 1
            uav.take_damage(uav.hp)  # an empty tank costs every health point it has left
            self.destroy_uav(uav, reason="out of fuel")

    # takes a UAV that has run out of health points out of the simulation: off the grid, so that it stops
    # blocking traffic and being drawn, and out of the scheduler, so that it takes no further steps. It
    # stays in self.uavs as a record of the team that started the run.
    def destroy_uav(self, uav, reason="collision"):
        self.uavs_lost += 1
        self.log.warning("UAV %d destroyed at %s after %d step(s): %s",
                         uav.unique_id, uav.pos, self.evaluation_timesteps_counter, reason)
        # a UAV destroyed while refilling would otherwise hold its slot at the base for good
        if self.base is not None:
            self.base.serving.pop(uav.unique_id, None)
        self.grid.remove_agent(uav)
        self.schedule.remove(uav)

    # method for collecting the partial view of every UAV still flying, in team order. This is the order
    # set_drone_dirs() uses as well, so a policy can return one action per entry of this list.
    def observations(self):
        return [uav.observe() for uav in self.active_uavs()]

    # method for obtaining each UAV partial observation. 'observations' can be passed in to avoid querying
    # the grid a second time when the caller already collected them.
    def state(self, observations=None):
        if observations is None:
            observations = self.observations()
        # this for loop obtains the amount of burning cells for each agent
        states = [observation.flat_states() for observation in observations]

        # this for loop adds zeros in those positions of the list that would correspond to cells that cannot be
        # observed. This is done when a UAV reaches an edge/corner, not getting the list in the corresponding format
        # Mesa framework asks for
        for st, _ in enumerate(states):
            counter = len(states[st])
            for i in range(counter, config.N_OBSERVATIONS):
                states[st].append(0)
        return states

    # Mesa framework native method, which is overwritten, necessary for setting next state of the simulation
    def step(self):
        self.datacollector.collect(self)

        # check if simulation ended, if so report MR1 and MR2 overall metrics, and stop stepping.
        # Otherwise, keep executing. Stopping is signalled through the Mesa 'running' flag rather than
        # sys.exit(), so that the visualization server survives the end of a run and the Reset button can
        # start a new one.
        # evaluation_timesteps_counter is incremented once per simulated step below, so reaching BATCH_SIZE
        # means exactly BATCH_SIZE steps have been taken and this call has nothing left to do
        if self.evaluation_timesteps_counter >= config.BATCH_SIZE:
            self.log.info(" --- MR1 --- ")
            self.log.info("%s", self.MR1_LIST)
            self.log.info(" --- MR2 --- ")
            self.log.info("%s", self.MR2_VALUE)
            self.log.info(" --- collisions --- ")
            self.log.info("%d, %d UAV(s) lost of %d", self.collisions, self.uavs_lost, len(self.uavs))
            if config.ACTIVATE_FUEL:
                self.log.info(" --- fuel --- ")
                self.log.info("%d UAV(s) ran out of fuel, tanks left: %s", self.uavs_out_of_fuel,
                              [round(uav.fuel, 1) for uav in self.uavs])
            self.running = False
            return

        # only the UAVs still flying observe, act and score; a destroyed one has left the run
        flying = self.active_uavs()
        if flying:
            # what each UAV can see at time t; keeps cell positions, so a policy can decide where to fly
            observations = self.observations()
            state = self.state(observations)  # s_t

            # the policy turns s_t into one action per UAV. Actions are chosen from the observations of the
            # current step and executed in the same step, when schedule.step() runs UAV.advance().
            self.new_direction = self.policy.select_actions(observations)  # a_t

            # TODO: algorithm/s calculation with partial state
            # reward = self.algorithm(state) # r_t+1

            # TODO: an EXAMPLE can be seen. However, your own implementations can be applied as well.
            self.MR1(state, flying)
            self.MR2()

            # It sets new directions for the UAV team
            self.set_drone_dirs()

        self.evaluation_timesteps_counter += 1

        # the wildfire starts at its own step, which lets a run begin before there is anything to monitor.
        # It is lit before the schedule runs, so that the cells around it already see it burning while they
        # take this step, exactly as they do for a fire lit at step 0.
        if not self.fire_started and self.evaluation_timesteps_counter >= self.fire_start_step:
            self.start_fire()

        # ignition probability of every cell, worked out for the whole grid in one go. It has to
        # happen after start_fire() and before the schedule runs, because SimultaneousActivation
        # executes every step() before any advance(), so every cell reads one and the same burning
        # snapshot, taken before anything moves.
        self.update_fire_probabilities()

        # execute each agent step() method
        self.schedule.step()

        # where the smoke is, worked out for the whole grid in one go. Unlike the ignition probabilities
        # above this belongs *after* the schedule, and the difference is not a tidiness question:
        #
        #   * the Smoke counters tick inside Fire.step(), and Fire.extinguish() clears them from inside
        #     UAV.dump_water(), so the source mask only settles once the schedule has run;
        #   * every reader is upstream of the schedule. observe() is called at the top of this method for
        #     the policy, and again before that by ModelSensor.read() for the managing system, which
        #     AdaptiveWildFireModel.step() runs ahead of super().step(). Both therefore read the mask this
        #     line left behind on the previous step -- one mask per step, so the two cannot be told
        #     different things about what the smoke hid. That invariant is the whole reason occlusion is a
        #     threshold rather than a draw.
        self.update_smoke()

        # the UAVs have finished moving, so whoever ended up sharing a cell has collided. Settled here
        # rather than inside UAV.advance(), because sharing a cell is a property of the grid: it is only
        # known once every UAV has moved, and it costs both of them the same whichever moved first.
        self.resolve_collisions()

        # the fuel each UAV burned was charged as it flew, so whoever ran the tank dry is settled now,
        # after the collisions: a UAV that both collided fatally and ran out on the same step has already
        # gone, and is counted against the collision rather than twice.
        self.resolve_fuel()

        # firefighting extension: losing the home base ends the run immediately
        if config.ACTIVATE_FIREFIGHTING and self.base is not None and self.base.is_destroyed() and not self.lost:
            self.lost = True
            self.running = False
            self.log.warning("home base destroyed after burning for %d steps: run lost at step %d",
                             self.base.burning_steps, self.evaluation_timesteps_counter)
