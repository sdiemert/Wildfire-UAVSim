"""An analyser that draws every line earlier than the default one does."""

# own python modules

from .heuristic import HeuristicAnalyzer


class CautiousAnalyzer(HeuristicAnalyzer):
    """The same measurements as HeuristicAnalyzer, reported sooner.

    Nothing here changes what is measured or how -- distance to the nearest fire the base can see, team
    mates inside the security distance, health and fuel. What changes is where the thresholds sit:

      * fire counts as threatening the base half again as far out (THREAT_SCALE)
      * the inner band, where the threat is level 2 rather than 1, is half the radius instead of a third
        (CLOSE_SHARE), so the team is committed to the base earlier
      * a base that has spent a third of its BHP is already treated urgently, rather than three fifths
        (URGENT_DAMAGE)
      * UAVs are called crowded at a quarter more than the security distance (CROWDING_SCALE), which asks
        for room before a collision is imminent rather than as it becomes so

    Whether reacting earlier is better is the experiment, not the assumption. Reacting to a fire that would
    have burned itself out spends UAV-steps that the wildfire at large would otherwise have got, and every
    threshold moved down here trades false alarms for warning. Pair it with a planner and measure:

        python3 headless.py --runs 30 --seed 1 --managing heuristic  --output a.json
        python3 headless.py --runs 30 --seed 1 --mape analyzer=cautious --output b.json
    """

    name = "cautious"

    URGENT_DAMAGE = 0.3
    THREAT_SCALE = 1.5
    CLOSE_SHARE = 0.5
    CROWDING_SCALE = 1.25
