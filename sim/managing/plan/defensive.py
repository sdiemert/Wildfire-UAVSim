"""A planner that spends the whole team on the home base sooner than the default one does."""

# own python modules

from .heuristic import HeuristicPlanner


class DefensivePlanner(HeuristicPlanner):
    """HeuristicPlanner with the base weighted over everything but destruction.

    Two rules change, and both are the same argument taken further. HeuristicPlanner's docstring records
    that having all dispersal outrank all defending lost runs, and that the order was reversed as a result.
    This planner asks whether that reversal went far enough:

      * **a bigger detachment at every threat level.** Half the team at level 1 and three quarters at level
        2, against a third and a half. The base is what ends the run when it is lost, and a fire that has
        got inside BASE_THREAT_RADIUS is already close enough that the UAVs sent late arrive after it.

      * **crowding no longer moves anybody** (DISPERSE_CROWDED). A crowded UAV keeps its mission and is
        kept from actually colliding by SuperPolicy's fleet wide traffic pass, which trims every action
        against the rest of the team whatever policy a UAV is flying. `disperse` is the stronger remedy of
        abandoning the mission until there is room, and this planner never thinks that is worth it. A UAV
        down to its last health point is still dispersed, because for that one a collision is destruction
        rather than damage, and rule 1 is not about crowding but about what is irreversible.

    The result should defend better and collide more. Which of those matters more is a question about the
    goals rather than about the code, so it is left as a managing system to select and measure rather than
    as a change to the default one:

        python3 headless.py --runs 30 --seed 1 --managing heuristic --output a.json
        python3 headless.py --runs 30 --seed 1 --managing defensive --output b.json
    """

    name = "defensive"

    DISPERSE_CROWDED = False
    THREAT_SHARES = {1: 0.5, 2: 0.75}
