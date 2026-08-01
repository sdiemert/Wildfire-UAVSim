# python libraries

import logging
import mesa
import matplotlib.pyplot as plt

# own python modules

import agents

# imported by name because 'policy' is also the name of the constructor argument and attribute below,
# which would shadow the module
from policy import RandomPolicy, build_policy

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
        # set Fire and wind agents (Smoke are created inside Fire agents as well)
        self.set_fire_agents()
        self.wind = agents.Wind()

        x_center = int(HEIGHT / 2)
        y_center = int(WIDTH / 2)

        self.new_direction_counter = 0
        self.evaluation_timesteps_counter = 0

        # create and configure UAV agents in the grid
        for a in range(0, self.NUM_AGENTS):
            aux_UAV = agents.UAV(self.unique_agents_id, self)
            y_center += a if a % 2 == 0 else -a
            self.grid.place_agent(aux_UAV, (x_center, y_center + 1))
            self.schedule.add(aux_UAV)
            self.unique_agents_id += 1

        # set Mesa framework management
        self.datacollector = mesa.DataCollector()
        self.new_direction = [0 for a in range(0, self.NUM_AGENTS)]

    # function that creates all fire agents in a grid
    def set_fire_agents(self):
        # obtain center position of the grid
        x_c = int(HEIGHT / 2)
        y_c = int(WIDTH / 2)
        x = [x_c]
        y = [y_c]
        for i in range(HEIGHT):
            for j in range(WIDTH):
                # decides to put a "tree" (fire agent) or not, if less than DENSITY_PROB
                # or if it is in the center of the grid
                if SYSTEM_RANDOM.random() < DENSITY_PROB or (i in x and j in y):
                    # only if it is in the center of the grid, Fire agent is set burning at the beginning, otherwise
                    # it is set to not burning
                    if i in x and j in y:
                        self.new_fire_agent(i, j, True)
                    else:
                        self.new_fire_agent(i, j, False)

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

    # manage directions obtained from the new_direction attribute, and make the UAV team move over the forest area
    def set_drone_dirs(self):
        # used for selecting the corresponding direction from new_direction attribute, for each UAV
        self.new_direction_counter = 0
        # searches for all UAV agents in scheduler, and set their new directions
        for agent in self.schedule.agents:
            if type(agent) is agents.UAV:
                agent.selected_dir = self.new_direction[self.new_direction_counter]
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
        # execute each agent step() method
        self.schedule.step()
