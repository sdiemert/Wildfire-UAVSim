"""The two ways the managing system is allowed to touch the managed system.

A sensor reads and an effector writes, and there is nothing else. Both are declared here, on the managing
side, and implemented on the managed side in sim/adapters.py -- which is the only module in the project
that imports both halves. Everything in between is the frozen data in contract.py.

Declaring the interfaces here rather than next to their implementations is deliberate. It means the
managing system depends on nothing but its own idea of what a sensor and an effector are, and the
simulation is what has to satisfy that idea. Swapping the simulation for a different one, or for a real
fleet, is then a matter of writing two new adapters and changing nothing else.
"""

# python libraries

from abc import ABC, abstractmethod


class Sensor(ABC):
    """Reads the managed system.

    The whole of what a managing system can learn comes through here, which is what makes a sensor worth
    being an interface rather than a function: what it chooses to report *is* the observability of the
    managed system, and changing it is the way to run the same managing system under a different one.
    """

    @abstractmethod
    def read(self):
        """Return a FleetSnapshot of the managed system as it stands right now.

        Returns:
            contract.FleetSnapshot. Must be safe to keep: the managing system stores snapshots in its
            Knowledge base and compares old ones against new, so a sensor must never hand back a view onto
            something the simulation goes on mutating. The frozen types in contract.py are what guarantee
            this, which is why a sensor builds them rather than passing model objects through.
        """


class Effector(ABC):
    """Writes to the managed system.

    An effector is a trust boundary as much as a channel. What it is handed may have come from a planner
    on the other side of a network, so it validates every directive before applying it and drops the ones
    it cannot make sense of, rather than raising: a managing system that has gone wrong should cost the run
    its adaptation quality, not end it.
    """

    @abstractmethod
    def apply(self, allocation):
        """Apply an Allocation to the managed system.

        Args:
            allocation: contract.Allocation. Directives naming a UAV that does not exist, one that has
                already been destroyed, a policy the simulation does not have, or parameters outside their
                bounds are rejected individually. The rest are still applied.

        Returns:
            int, how many directives were actually applied. Fewer than were asked for means some were
            rejected, and the effector will have logged each one.
        """
