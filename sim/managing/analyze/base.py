"""The A of MAPE-K: turn a reading into a judgement about what is wrong.

Analysis is kept apart from planning on purpose. What counts as a threatened base or a crowded UAV is a
statement about the managed system, and stays the same whoever is doing the planning; what to *do* about it
is where a heuristic, a solver and a remote service differ. Splitting them means one analyser can be paired
with several planners, which is what a managing system in systems.py is composed out of.
"""

# python libraries

from abc import ABC, abstractmethod


class Analyzer(ABC):
    """Decides what, if anything, is wrong with the managed system."""

    # the name this analyser is registered and selected under; see sim/managing/analyze/__init__.py
    name = "analyzer"

    @abstractmethod
    def analyze(self, snapshot, knowledge):
        """Return the Symptoms present in a snapshot.

        Args:
            snapshot: contract.FleetSnapshot, the reading just taken.
            knowledge: the Knowledge base, for anything that needs more than one reading to see -- whether
                the fire near the base is closing in, for instance, which a single snapshot cannot say.

        Returns:
            contract.Symptoms. Symptoms.requires_adaptation() being False short circuits the loop before
            Plan runs at all.
        """

    def __str__(self):
        return self.name
