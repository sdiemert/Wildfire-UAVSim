"""The agents that stand on the grid.

One module per kind of agent, all of them mesa.Agent subclasses that the scheduler steps:

  Fire         one cell of vegetation, which holds the fuel and does the burning
  UAV          one drone, which observes, flies and dumps water
  Base         the home base of the firefighting extension, where UAVs refill and refuel
  BaseTile     one non-anchor cell of the base footprint, so that the whole of it is drawn
  OutBuilding  a building on the map that burns and is worth defending

The wind and the smoke are not here: they hold no cell and are not stepped. The wind, and the per cell
timer that says whether a cell is *raising* smoke, live in sim/environment.py; where that smoke then drifts
to, which is what decides whether a cell can be observed at all, is worked out over the whole grid at once
in sim/smoke.py.

Everything is re-exported, so `from sim import agents` then `agents.UAV` reaches any of them without
having to know which module it is in. The identity of these classes matters, because the code tests agent
kinds with `type(agent) is Fire` rather than isinstance; re-exporting binds the same class object, so those
checks are unaffected by where a caller imports from.

These modules read their settings through `config.` at the point of use rather than copying the values in
with a star import, which is what lets a runner or a test override a constant and have the whole simulation
pick it up.
"""

from sim.agents.base import Base, BaseTile
from sim.agents.fire import Fire
from sim.agents.out_building import OutBuilding
from sim.agents.uav import UAV

__all__ = ["Base", "BaseTile", "Fire", "OutBuilding", "UAV"]
