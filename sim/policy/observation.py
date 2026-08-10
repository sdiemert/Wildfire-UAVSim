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

    'water' is the loads aboard and 'water_capacity' what a full load is, read through water_fraction().
    They matter to more than the firefighting: the fuel a step costs is multiplied by the payload, so a
    policy estimating how far its fuel will take it has to pass water_fraction() to fuel_burn_cost() along
    with the distance. 'has_water' stays the boolean the ladders are written against.

    With the positioning error extension on, 'pos' is the position the UAV *measured* rather than where it
    really is, and each entry of 'uav_positions' is what that team mate measured about itself; 'cells',
    'base_pos', 'base_cells' and 'building_positions' stay in true grid coordinates, because the error
    belongs to the receiver and not to the camera. A policy needs no special case for it -- it is written
    against the belief either way -- but two things stop holding that a policy might otherwise assume: at_base()
    can be wrong in both directions, and a cell occupied() calls clear can have a UAV on it after all.
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

    # loads of water aboard and what a full load is, which is what the fuel burn is charged against.
    # 'water_capacity' is None on an Observation built without it, and water_fraction() then falls back to
    # has_water, so a policy reading the payload works either way
    water: int = 0
    water_capacity: int = None
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

    # how much of a full load of water this UAV is carrying, as a fraction. The fuel burn is charged
    # against exactly this, so a policy working out what a step will cost passes it straight to
    # formulas.fuel_burn_cost() and gets the number the model will charge. An Observation built without a
    # capacity -- which is every one a policy test writes by hand -- falls back to the boolean, so it still
    # answers 1.0 for a UAV carrying water and 0.0 for an empty one.
    def water_fraction(self):
        if not self.water_capacity:
            return 1.0 if self.has_water else 0.0
        return max(0.0, min(1.0, self.water / self.water_capacity))

    # whether another UAV in view is standing on a given cell, which is where flying would be a collision
    def occupied(self, cell):
        return tuple(cell) in {tuple(position) for position in self.uav_positions}

    # the flat 0/1 list the rest of the model already expects, in observation order
    def flat_states(self):
        return [burning for _, burning in self.cells]

    # number of burning cells in view
    def burning_count(self):
        return sum(burning for _, burning in self.cells)
