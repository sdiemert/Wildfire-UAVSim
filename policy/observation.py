"""What a single UAV can see at one time step."""

# python libraries

from dataclasses import dataclass, field


@dataclass
class Observation:
    """One UAV's partial view of the grid, as produced by UAV.observe().

    'cells' holds (position, burning) for every observed cell that contains vegetation. Cells without a Fire
    agent are absent, which is why flat_states() can be shorter than N_OBSERVATIONS near the grid edges.
    """

    uav_id: int
    pos: tuple
    cells: list = field(default_factory=list)

    # the fields below belong to the firefighting extension and keep their defaults when it is switched off
    has_water: bool = False
    base_pos: tuple = None
    building_positions: list = field(default_factory=list)

    # positions of the cells that are on fire right now
    def burning_positions(self):
        return [position for position, burning in self.cells if burning]

    # whether this UAV is currently standing on the home base
    def at_base(self):
        return self.base_pos is not None and tuple(self.pos) == tuple(self.base_pos)

    # the flat 0/1 list the rest of the model already expects, in observation order
    def flat_states(self):
        return [burning for _, burning in self.cells]

    # number of burning cells in view
    def burning_count(self):
        return sum(burning for _, burning in self.cells)
