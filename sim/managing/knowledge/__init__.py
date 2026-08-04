"""Knowledge bases: what a managing system remembers between evaluations.

To add your own:

  1. create sim/managing/knowledge/my_knowledge.py with a Knowledge subclass that has a unique 'name'
  2. import it below and add the class to KNOWLEDGE_BASES

It can then be named by a managing system in sim/managing/systems.py, selected for one run with
`--mape knowledge=my-knowledge`, and is covered by the parametrised tests in
tests/managing/test_systems.py without any further change.

The K is not one of the four steps, but it is the thing all four share, and it is the only mutable thing on
the managing side -- so what it chooses to remember bounds what any analyser or planner built over it can
possibly know. That makes it worth varying: a knowledge base that keeps the whole run rather than a bounded
window, one that forgets between evaluations, or one that damps decisions differently are all different
managing systems, whatever else they are composed of.

The damping is the clearest case and is already in use. Hysteresis lives here rather than in the planner,
because how sure you have to be before acting is a question about what you remember; `reactive` in
systems.py is the default components with it turned off, and nothing but the Knowledge base changed.
"""

# own python modules

from ..registry import Registry
from .base import Knowledge

# every knowledge base a managing system may be composed from
KNOWLEDGE_BASES = Registry("knowledge base", (Knowledge,))

__all__ = ["KNOWLEDGE_BASES", "Knowledge"]
