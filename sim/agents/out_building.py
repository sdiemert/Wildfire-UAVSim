# python libraries

import mesa

# own python modules

import config

from sim.agents.fire import Fire


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
