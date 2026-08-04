"""The P of MAPE-K: decide what the team should be flying.

Planning is where the interesting decisions are, and a planner is pluggable so that the heuristic in
heuristic.py can be replaced by a solver, a learned policy or anything else without the rest of the loop
noticing. Which one a managing system uses is named in its entry in sim/managing/systems.py.

Note that this is not where local and remote part company. A managing system is remote as a whole or not
at all: when MANAGING_SYSTEM is 'remote', the analysis, the planning and the Knowledge base are all on the
server, and no Planner is built in this process. See sim/managing/remote.py for why the boundary is drawn
around the whole loop rather than around this one step.
"""

# python libraries

from abc import ABC, abstractmethod


class Planner(ABC):
    """Turns a reading and a diagnosis into orders for the team."""

    # identifier used by the factory in sim/managing/loop.py and reported in the logs
    name = "planner"

    @abstractmethod
    def plan(self, snapshot, symptoms, knowledge):
        """Return the Allocation the team should be flying.

        Args:
            snapshot: contract.FleetSnapshot, what the sensor reported.
            symptoms: contract.Symptoms, what the analyser made of it. A planner is free to ignore this and
                read the snapshot itself.
            knowledge: the Knowledge base. A planner reads it for history and, importantly, calls
                knowledge.settled() to apply hysteresis, so that a decision has to hold for a couple of
                evaluations before the team is actually turned around.

        Returns:
            contract.Allocation, holding one UavDirective per UAV it has an opinion about. A UAV left out
            keeps whatever it is already flying, so a planner that only wants to move one UAV may return a
            single directive.

            Every directive is validated by the effector before it reaches the simulation, so a planner
            cannot break a run by naming a policy that does not exist -- but it will have its directive
            dropped, so it should not try.
        """

    def __str__(self):
        return self.name
