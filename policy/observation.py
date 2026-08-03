"""What a single UAV can see at one time step."""

# python libraries

from dataclasses import dataclass, field

# own python modules

# see the note in random_policy.py about importing config as a module
import config


@dataclass
class Observation:
    """One UAV's partial view of the grid, as produced by UAV.observe().

    'cells' holds (position, burning) for every observed cell that contains vegetation. Cells without a Fire
    agent are absent, which is why flat_states() can be shorter than N_OBSERVATIONS near the grid edges.

    'uav_positions' holds the cells the other UAVs in view are standing on. Two UAVs that end a step on the
    same cell collide and lose health points, so this is what a policy needs to keep its team apart; it
    exists whether or not the firefighting extension is switched on.

    'fuel' is what is left in the tank, and 'fuel_capacity' what a full one holds. Both are None when the
    fuel extension is switched off, which is what tells a policy that fuel is not being tracked at all
    rather than that the tank is empty; fuel_fraction() and low_fuel() answer sensibly either way.
    """

    uav_id: int
    pos: tuple
    cells: list = field(default_factory=list)
    uav_positions: list = field(default_factory=list)

    # the fields below belong to the fuel extension and are None when it is switched off
    fuel: float = None
    fuel_capacity: float = None

    # the fields below belong to the firefighting extension and keep their defaults when it is switched off
    has_water: bool = False
    base_pos: tuple = None
    base_cells: list = field(default_factory=list)
    building_positions: list = field(default_factory=list)

    # positions of the cells that are on fire right now
    def burning_positions(self):
        return [position for position, burning in self.cells if burning]

    # every cell of the home base footprint, which is shared airspace: any number of UAVs may sit on it
    # without colliding. Falls back to the anchor cell alone for an Observation built without a footprint.
    def base_footprint(self):
        if self.base_cells:
            return [tuple(cell) for cell in self.base_cells]
        return [] if self.base_pos is None else [tuple(self.base_pos)]

    # whether this UAV is currently standing on the home base
    def at_base(self):
        return tuple(self.pos) in set(self.base_footprint())

    # how much of a full tank this UAV has left, as a fraction. Reports a full tank when fuel is not being
    # tracked, so that a policy which reads it flies exactly as it did before the extension existed.
    def fuel_fraction(self):
        if self.fuel is None or not self.fuel_capacity:
            return 1.0
        return max(0.0, min(1.0, self.fuel / self.fuel_capacity))

    # whether this UAV has reached the reserve it should be turning for home on. Advisory: nothing in the
    # simulation enforces it, and a policy is free to ignore it and fly until the tank is dry. False
    # whenever fuel is not being tracked. UAV_FUEL_RESERVE is read at call time, so overriding it works.
    def low_fuel(self):
        if self.fuel is None:
            return False
        return self.fuel_fraction() <= config.UAV_FUEL_RESERVE

    # whether another UAV in view is standing on a given cell, which is where flying would be a collision
    def occupied(self, cell):
        return tuple(cell) in {tuple(position) for position in self.uav_positions}

    # the flat 0/1 list the rest of the model already expects, in observation order
    def flat_states(self):
        return [burning for _, burning in self.cells]

    # number of burning cells in view
    def burning_count(self):
        return sum(burning for _, burning in self.cells)
