"""Abstract interface that every UAV policy implements."""

# python libraries

from abc import ABC, abstractmethod


class Policy(ABC):
    """Decides which direction each UAV flies at a given time step.

    Subclasses set a unique 'name', which is what the --policy command line option and the dropdown on the
    web interface use to identify them, and implement select_actions().
    """

    # identifier used by the registry, the CLI and the web interface dropdown
    name = "policy"

    @abstractmethod
    def select_actions(self, observations):
        """Return one action per UAV, ordered exactly like 'observations'.

        Args:
            observations: list of Observation, one per UAV, in scheduler order. Each one describes only
                what that UAV can see, so a policy cannot cheat by reading the whole grid.

        Returns:
            list of action indices. Movement actions are ACTION_RIGHT, ACTION_DOWN, ACTION_LEFT and
            ACTION_UP; ACTION_STAY holds the current position. All are defined in config.py.
        """

    def __str__(self):
        return self.name
