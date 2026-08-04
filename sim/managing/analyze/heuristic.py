"""The analyser the managing system uses unless it is told to use another one."""

# own python modules

# see the note in sim/policy/random_policy.py about importing config as a module
import config

from ..contract import Symptoms
from .base import Analyzer


class HeuristicAnalyzer(Analyzer):
    """Reads a snapshot against the two things the managing system is responsible for.

    **The base burning down.** Threat runs 0 to 3. It is driven by how close the nearest fire the base can
    see is, measured against BASE_THREAT_RADIUS, and raised to its maximum once the base has actually
    started taking damage. A fire that is getting closer rather than further away counts for one level more
    than its distance alone would give it, which is what the Knowledge base is consulted for: a front
    sweeping toward the base and a front burning itself out ten cells away look identical in one snapshot.

    **UAVs colliding.** A UAV is crowded when it can see team mates closer than SECURITY_DISTANCE, and the
    count of them is how badly. That is the same measure MR2 scores a run on, so the analyser is looking at
    exactly the quantity the run is judged by, rather than a proxy for it.

    Separately, a UAV low on health points or nearly out of fuel is reported as at risk. It has not done
    anything wrong and may not be crowded at all, but it is worth more to the run intact than busy, and a
    planner that knows which UAVs those are can spend the sound ones instead.

    Every threshold below is a class attribute rather than a literal, so that an analyser which measures the
    same things and draws its lines somewhere else is a subclass of a few lines rather than a copy of this
    one. cautious.py is that subclass.
    """

    name = "heuristic"

    # the share of BHP already spent past which the base is treated one threat level more urgently at the
    # same distance, because it has that much less margin for the next front
    URGENT_DAMAGE = 0.6

    # what BASE_THREAT_RADIUS is multiplied by before a fire counts as threatening the base at all. Above 1
    # is an analyser that starts worrying further out.
    THREAT_SCALE = 1.0

    # the share of that radius inside which a fire is threat level 2 rather than 1
    CLOSE_SHARE = 1 / 3

    # what SECURITY_DISTANCE is multiplied by before two UAVs count as crowding each other. Above 1 is an
    # analyser that asks for more room than a collision strictly requires.
    CROWDING_SCALE = 1.0

    def analyze(self, snapshot, knowledge=None):
        flying = snapshot.alive()

        return Symptoms(
            base_threat=self.base_threat(snapshot, knowledge),
            threat_distance=self.threat_distance(snapshot),
            crowding=self.crowding(flying, snapshot.base),
            at_risk=self.at_risk(flying),
            lost=len(snapshot.uavs) - len(flying),
            flying=len(flying),
        )

    # how far the nearest fire the base knows about is, or infinity when there is no base or no fire
    def threat_distance(self, snapshot):
        if snapshot.base is None:
            return float("inf")
        return snapshot.base.nearest_fire_distance()

    # how badly the home base is threatened *right now*, 0 to 3.
    #
    # It has to be "right now" rather than "ever". BHP damage is cumulative and never repaid, so a base
    # that has been alight once carries burning_steps > 0 for the rest of the run; reading the threat off
    # that counter pins it at its maximum from the first point of damage onward, and the managing system
    # then holds the whole team over a base that is no longer burning while the wildfire it was supposed to
    # be fighting spreads unopposed -- and duly comes back and finishes the base off. The accumulated
    # damage belongs in this judgement as *urgency*, not as the threat itself.
    def base_threat(self, snapshot, knowledge=None):
        base = snapshot.base
        if base is None:  # firefighting off: there is no base to lose
            return 0
        if base.destroyed:
            return 3

        distance = base.nearest_fire_distance()
        radius = config.BASE_THREAT_RADIUS * self.THREAT_SCALE
        if distance > radius:  # nothing the base can see is close enough to matter
            return 0

        if distance <= 0:  # the footprint itself is alight, which is damage being taken this very step
            return 3

        # inside CLOSE_SHARE of the radius is level 2, inside the whole of it level 1
        level = 2 if distance <= radius * self.CLOSE_SHARE else 1

        # a front that is closing counts for one more than where it happens to have got to. This is what
        # the Knowledge base is for: one snapshot cannot tell a fire sweeping toward the base from one
        # burning itself out the same distance away.
        if knowledge is not None and knowledge.base_threat_rising():
            level += 1

        # a base that has already spent most of the damage it can survive has less margin for the next
        # front than a pristine one, and is worth treating one level more urgently at the same distance
        if base.damage_fraction() >= self.URGENT_DAMAGE:
            level += 1

        return min(3, level)

    # uav id -> how many team mates it can see closer than SECURITY_DISTANCE. UAVs that can see nobody that
    # close are left out entirely, so an empty mapping means the team is flying safely.
    #
    # The home base is left out of this on both sides. Its footprint is shared airspace: any number of UAVs
    # may sit on it without colliding, which is what lets the whole team launch from it and queue on it to
    # refill (see WildFireModel.resolve_collisions()). Counting that as crowding would report the team as
    # being in danger on the first step of every run, when they are simply all still on the pad, and would
    # have the managing system scatter them before they had done anything.
    def crowding(self, flying, base=None):
        limit_squared = (config.SECURITY_DISTANCE * self.CROWDING_SCALE) ** 2
        shared = set(base.cells) if base is not None else set()
        crowded = {}

        for report in flying:
            if report.pos is None or report.pos in shared:
                continue
            close = sum(1 for other in report.sees_uavs
                        if other not in shared
                        and (other[0] - report.pos[0]) ** 2 + (other[1] - report.pos[1]) ** 2
                        < limit_squared)
            if close:
                crowded[report.uav_id] = close
        return crowded

    # the UAVs worth preserving rather than spending: down to their last health point, or at or below the
    # fuel reserve they were meant to turn for home on
    def at_risk(self, flying):
        at_risk = []
        for report in flying:
            if report.hp <= 1 or report.fuel_fraction() <= config.UAV_FUEL_RESERVE:
                at_risk.append(report.uav_id)
        return tuple(at_risk)
