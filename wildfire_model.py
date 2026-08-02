# python libraries

import logging
import mesa
import matplotlib.pyplot as plt

# own python modules

import agents

# imported by name because 'policy' is also the name of the constructor argument and attribute below,
# which would shadow the module
from policy import Action, RandomPolicy, build_policy

from config import *


# class WildFireModel holds methods for managing the main logic of the grid, such as the main execution loop,
# setting agents, methods for checking the state of the grid, etc
class WildFireModel(mesa.Model):

    # constructor. 'log' lets a runner (see headless.py) hand in a run specific logger, so that agent messages
    # are attributed to the simulation they came from. When it isn't given, messages go to the shared
    # "wildfire.model" logger, which has no handlers unless something configured it, and so stays silent.
    def __init__(self, log=None, policy=None):

        plt.ion()

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
        self.NUM_AGENTS = NUM_AGENTS
        print(self.NUM_AGENTS)

        self.MR1_LIST = [0.0 for i in range(0, self.NUM_AGENTS)]
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

        self.unique_agents_id = 0
        # Inverted width and height order, because of matrix accessing purposes, like in many examples:
        #   https://snyk.io/advisor/python/Mesa/functions/mesa.space.MultiGrid
        # set some Mesa framework management
        self.grid = mesa.space.MultiGrid(HEIGHT, WIDTH, False)
        self.schedule = mesa.time.SimultaneousActivation(self)
        # where and when the wildfire starts. Both are resolved once per run, before the Fire agents are
        # created, because the ignition cell has to exist whatever the tree density decides
        self.fire_start_pos = self.resolve_fire_start_position()
        self.fire_start_step = self.resolve_fire_start_step()
        self.fire_started = False
        # set Fire and wind agents (Smoke are created inside Fire agents as well)
        self.set_fire_agents()
        self.wind = agents.Wind()

        x_center = int(HEIGHT / 2)
        y_center = int(WIDTH / 2)

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
        if ACTIVATE_FIREFIGHTING:
            self.set_base()
            self.set_out_buildings()

        # create and configure UAV agents in the grid
        for a in range(0, self.NUM_AGENTS):
            aux_UAV = agents.UAV(self.unique_agents_id, self)
            if ACTIVATE_FIREFIGHTING:
                # every UAV starts from the home base, with a full load of water
                self.grid.place_agent(aux_UAV, self.base.pos)
            else:
                y_center += a if a % 2 == 0 else -a
                self.grid.place_agent(aux_UAV, (x_center, y_center + 1))
            self.schedule.add(aux_UAV)
            self.unique_agents_id += 1

        # set Mesa framework management
        self.datacollector = mesa.DataCollector()
        self.new_direction = [0 for a in range(0, self.NUM_AGENTS)]

    # function that gives the cells the home base covers, at BASE_POSITION or a quarter into the grid by
    # default, as a BASE_SIZE footprint anchored on that position and clipped to the grid. It depends on
    # nothing but the configuration and the grid size, so that it can be consulted before the base agent
    # exists: a random ignition cell has to know which cells the base will occupy.
    def base_footprint(self):
        if not ACTIVATE_FIREFIGHTING:
            return []

        anchor = tuple(BASE_POSITION if BASE_POSITION is not None else (int(HEIGHT / 4), int(WIDTH / 4)))
        if self.grid.out_of_bounds(anchor):
            raise ValueError(f"BASE_POSITION {anchor} is outside the {HEIGHT}x{WIDTH} grid")

        # the anchor comes first, so that it stays the cell the Base agent itself sits on
        footprint = [anchor]
        for dx in range(BASE_SIZE[0]):
            for dy in range(BASE_SIZE[1]):
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
                      anchor, len(footprint), BHP)

    # function that scatters the out buildings randomly over the grid, avoiding the base cell and any cell
    # that already holds a building
    def set_out_buildings(self):
        taken = set(self.base.cells) if self.base is not None else set()
        candidates = [(x, y) for x in range(HEIGHT) for y in range(WIDTH) if (x, y) not in taken]
        # more buildings than free cells cannot be placed; ask for what fits
        wanted = min(NUM_OUT_BUILDINGS, len(candidates))
        for position in SYSTEM_RANDOM.sample(candidates, wanted):
            building = agents.OutBuilding(self.unique_agents_id, self)
            self.unique_agents_id += 1
            self.schedule.add(building)
            self.grid.place_agent(building, position)
            self.out_buildings.append(building)
        if wanted:
            self.log.info("%d out building(s) placed at %s", wanted,
                          [building.pos for building in self.out_buildings])

    # looks a UAV up by its unique id, used by the base to check who is still standing on it
    def uav_by_id(self, uav_id):
        for agent in self.schedule.agents:
            if type(agent) is agents.UAV and agent.unique_id == uav_id:
                return agent
        return None

    # function that decides which cell the wildfire starts from, from FIRE_START_POSITION
    def resolve_fire_start_position(self):
        setting = FIRE_START_POSITION

        if setting is None:  # the centre of the grid
            return int(HEIGHT / 2), int(WIDTH / 2)

        if isinstance(setting, str):
            if setting.lower() != "random":
                raise ValueError("FIRE_START_POSITION must be None, 'random' or an (x, y) cell, "
                                 f"got {setting!r}")
            # the home base is left out of the draw: a fire lit on top of it would have the base alight
            # from the first step, and BHP would run out before the UAVs could do anything about it
            reserved = set(self.base_footprint())
            candidates = [(x, y) for x in range(HEIGHT) for y in range(WIDTH) if (x, y) not in reserved]
            if not candidates:
                raise ValueError("no cell is free of the home base to start the fire from")
            return SYSTEM_RANDOM.choice(candidates)

        cell = tuple(setting)
        if self.grid.out_of_bounds(cell):
            raise ValueError(f"FIRE_START_POSITION {cell} is outside the {HEIGHT}x{WIDTH} grid")
        return cell

    # function that decides which step the wildfire starts at, from FIRE_START_STEP
    def resolve_fire_start_step(self):
        setting = FIRE_START_STEP

        # anywhere in the run. BATCH_SIZE is how long a run lasts, so the fire always keeps at least one
        # step to spread in
        if setting is None or (isinstance(setting, str) and setting.lower() == "random"):
            return SYSTEM_RANDOM.randrange(max(1, BATCH_SIZE))

        if isinstance(setting, (tuple, list)):  # a random step inside a range the user gave
            if len(setting) != 2:
                raise ValueError(f"FIRE_START_STEP range must be (first, last), got {setting!r}")
            first, last = max(0, int(setting[0])), max(0, int(setting[1]))
            if first > last:
                raise ValueError(f"FIRE_START_STEP range {setting!r} ends before it starts")
            return SYSTEM_RANDOM.randint(first, last)

        if isinstance(setting, str):
            raise ValueError("FIRE_START_STEP must be a step, a (first, last) range or 'random', "
                             f"got {setting!r}")

        return max(0, int(setting))  # one exact step

    # function that creates all fire agents in a grid
    def set_fire_agents(self):
        for i in range(HEIGHT):
            for j in range(WIDTH):
                # decides to put a "tree" (fire agent) or not, if less than DENSITY_PROB. The ignition cell
                # always gets one, whatever the density decides, because the fire has to start somewhere
                ignition_cell = (i, j) == self.fire_start_pos
                if SYSTEM_RANDOM.random() < DENSITY_PROB or ignition_cell:
                    # the ignition cell is created already burning when the fire starts at step 0, otherwise
                    # every cell starts unburnt and start_fire() lights it once the run reaches that step
                    self.new_fire_agent(i, j, ignition_cell and self.fire_start_step <= 0)

        if self.fire_start_step <= 0:
            self.fire_started = True
            self.log.info("fire lit at %s at the start of the run", self.fire_start_pos)
        else:
            self.log.info("fire will start at %s at step %d", self.fire_start_pos, self.fire_start_step)
            if self.fire_start_step >= BATCH_SIZE:
                self.log.warning("FIRE_START_STEP %d is not reached in a %d step run: nothing will burn",
                                 self.fire_start_step, BATCH_SIZE)

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

    # manage actions obtained from the new_direction attribute, and make the UAV team move over the forest area
    def set_drone_dirs(self):
        # used for selecting the corresponding action from new_direction attribute, for each UAV
        self.new_direction_counter = 0
        # searches for all UAV agents in scheduler, and set their new direction and speed. What the policy
        # returned is coerced into an Action, so a policy that only gives a direction still works.
        for agent in self.schedule.agents:
            if type(agent) is agents.UAV:
                action = Action.coerce(self.new_direction[self.new_direction_counter])
                agent.selected_dir = action.direction
                agent.selected_speed = action.speed
                self.new_direction_counter += 1

    # this method obtains effective wildfire monitoring metric (MR1) for time step t
    def MR1(self, state):
        # total amount of burning cells from state variable
        MR1_reward = [sum(aux_state) for aux_state in state]
        # normalized reward amount for each UAV state
        reward = [normalize(float(reward), N_OBSERVATIONS, 1, 0) for reward in MR1_reward]
        # MR1_list with added rewards
        self.MR1_LIST = [a + b for a, b in zip(self.MR1_LIST, reward)]

    # this method obtains collision risk avoidance metric (MR2) for time step t
    def MR2(self):
        counter = 0
        # get UAV agents from scheduler
        UAV_agents = [agent for agent in self.schedule.agents if type(agent) is agents.UAV]

        # checks number of interactions for each UAV with others
        for idx, agent in enumerate(UAV_agents):
            aux_agents_positions = UAV_agents.copy()
            del aux_agents_positions[idx]

            # checks number of interactions for one UAV
            for a in aux_agents_positions:
                x1 = agent.pos[0]
                y1 = agent.pos[1]
                x2 = a.pos[0]
                y2 = a.pos[1]
                # Euclidean distance between two UAV grid positions
                distance = euclidean_distance(x1, y1, x2, y2)
                # if distance between the two UAV is less than the defined security distance, add 1 to the counter
                if distance < SECURITY_DISTANCE:
                    counter += 1
        self.MR2_VALUE += counter // 2  # remove duplicate interactions

    # method for collecting the partial view of every UAV, in scheduler order. This is the order
    # set_drone_dirs() uses as well, so a policy can return one action per entry of this list.
    def observations(self):
        return [agent.observe() for agent in self.schedule.agents if type(agent) is agents.UAV]

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
            for i in range(counter, N_OBSERVATIONS):
                states[st].append(0)
        return states

    # Mesa framework native method, which is overwritten, necessary for setting next state of the simulation
    def step(self):
        self.datacollector.collect(self)

        # check if simulation ended, if so report MR1 and MR2 overall metrics, and stop stepping.
        # Otherwise, keep executing. Stopping is signalled through the Mesa 'running' flag rather than
        # sys.exit(), so that the visualization server survives the end of a run and the Reset button can
        # start a new one.
        if BATCH_SIZE == self.evaluation_timesteps_counter - 1:
            self.log.info(" --- MR1 --- ")
            self.log.info("%s", self.MR1_LIST)
            self.log.info(" --- MR2 --- ")
            self.log.info("%s", self.MR2_VALUE)
            self.running = False
            return

        if sum(isinstance(i, agents.UAV) for i in self.schedule.agents) > 0:
            # what each UAV can see at time t; keeps cell positions, so a policy can decide where to fly
            observations = self.observations()
            state = self.state(observations)  # s_t

            # the policy turns s_t into one action per UAV. Actions are chosen from the observations of the
            # current step and executed in the same step, when schedule.step() runs UAV.advance().
            self.new_direction = self.policy.select_actions(observations)  # a_t

            # TODO: algorithm/s calculation with partial state
            # reward = self.algorithm(state) # r_t+1

            # TODO: an EXAMPLE can be seen. However, your own implementations can be applied as well.
            self.MR1(state)
            self.MR2()

            # It sets new directions for the UAV team
            self.set_drone_dirs()

        self.evaluation_timesteps_counter += 1

        # the wildfire starts at its own step, which lets a run begin before there is anything to monitor.
        # It is lit before the schedule runs, so that the cells around it already see it burning while they
        # take this step, exactly as they do for a fire lit at step 0.
        if not self.fire_started and self.evaluation_timesteps_counter >= self.fire_start_step:
            self.start_fire()

        # execute each agent step() method
        self.schedule.step()

        # firefighting extension: losing the home base ends the run immediately
        if ACTIVATE_FIREFIGHTING and self.base is not None and self.base.is_destroyed() and not self.lost:
            self.lost = True
            self.running = False
            self.log.warning("home base destroyed after burning for %d steps: run lost at step %d",
                             self.base.burning_steps, self.evaluation_timesteps_counter)
