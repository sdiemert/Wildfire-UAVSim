# python libraries

import mesa

# own python modules

import config

from sim.agents.fire import Fire


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
