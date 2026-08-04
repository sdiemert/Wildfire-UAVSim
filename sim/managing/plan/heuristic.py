"""The planner the managing system uses unless it is told to use another one."""

# python libraries

import math

# own python modules

# see the note in sim/policy/random_policy.py about importing config as a module
import config

from ..contract import Allocation, UavDirective
from .base import Planner


class HeuristicPlanner(Planner):
    """Allocates policies by a short list of rules, in strict order of precedence.

    The rules, applied to every UAV still flying:

      1. **down to its last health point -> `disperse`.** One more collision destroys this UAV, and a
         destroyed UAV is worth nothing to either goal ever again. Nothing outranks this, because nothing
         else is irreversible for the UAV in question.

      2. **the base is threatened -> the UAVs nearest it fly `defend-base`.** How many of them scales with
         the threat: a third of the team at level 1, half at level 2, all of them at level 3. Nearest first,
         because they are the ones that can reach the front before it reaches the base.

      3. **crowded -> `disperse`.** A UAV flying closer to a team mate than SECURITY_DISTANCE is asked to
         open the gap, unless it was picked as a defender above.

      4. **everything else -> DEFAULT_UAV_POLICY.** Normally `firefighter`, which fights the wildfire at
         large. This is what the team does when nothing is going wrong, and it is what a UAV goes back to
         as soon as its own trouble has passed.

    Rules 2 and 3 are in that order because losing the base ends the run and a collision does not. An
    earlier version had all dispersal outrank all defending, on the reasoning that equipment comes first;
    it lost runs where the base was already alight and the whole team politely spread out instead of
    putting the fire out. Crowding is also the symptom the managed system already handles on its own:
    SuperPolicy trims every action against the rest of the fleet whatever policy a UAV is flying, so a
    crowded defender is still kept from actually colliding. `disperse` is the stronger remedy of giving up
    on the mission until there is room, and it is not worth the base.

    Every decision is then put through the Knowledge base's hysteresis, so a UAV is only actually turned
    around once the same decision has been reached ADAPTATION_HYSTERESIS evaluations running. A UAV whose
    decision has not settled is left out of the allocation entirely, which leaves it flying what it already
    was -- the managing system says nothing rather than saying something it is about to take back.

    The rules are deliberately legible rather than clever. This planner is the reference implementation and
    the fallback for the remote one, so what matters most about it is that its decisions can be read off
    the rationale it writes and checked against what the run then did.

    defensive.py is the same shape with rules 2 and 3 weighted differently, and is what an argument about
    that weighting is settled with. static.py is the planner that does none of this, and is what an
    argument about whether any of it helps is settled with.
    """

    name = "heuristic"

    # whether rule 3 applies at all: a planner that would rather keep a crowded UAV on the mission and let
    # SuperPolicy's traffic pass keep it from actually colliding turns this off
    DISPERSE_CROWDED = True

    # how much of the team each base threat level is worth, as a share of the UAVs still able to fly. Level
    # 3 is not listed because it is always the whole team: the base is alight and there is nothing else
    # left worth doing.
    THREAT_SHARES = {1: 1 / 3, 2: 0.5}

    def plan(self, snapshot, symptoms, knowledge=None):
        flying = snapshot.alive()
        if not flying:
            return Allocation(step=snapshot.step, rationale="no UAVs left flying")

        wanted = self.decide(snapshot, symptoms, flying)

        # hysteresis: only the decisions that have held long enough are actually issued
        directives = []
        for report in flying:
            policy_name, params = wanted[report.uav_id]
            if knowledge is None or knowledge.settled(report.uav_id, policy_name, report.policy):
                directives.append(UavDirective(uav_id=report.uav_id, policy=policy_name, params=params))

        return Allocation(step=snapshot.step, directives=tuple(directives),
                          rationale=self.rationale(symptoms, wanted, len(directives), len(flying)))

    # works out what every UAV ought to be flying, before hysteresis has a say. Returns
    # {uav id: (policy name, params dict)}, with an entry for every UAV still flying. The rules are applied
    # weakest first, each one writing over what the one before it decided.
    def decide(self, snapshot, symptoms, flying):
        wanted = {}

        # rule 4, the floor everything else is written over
        for report in flying:
            wanted[report.uav_id] = (config.DEFAULT_UAV_POLICY, {})

        # rule 3: crowded UAVs open the gap
        if self.DISPERSE_CROWDED:
            for report in flying:
                if report.uav_id in symptoms.crowding:
                    wanted[report.uav_id] = ("disperse", self.disperse_params(report))

        # rule 2: defenders, nearest the base first. Written over rule 3, because the base being lost ends
        # the run and a collision does not; a defender that is crowded is still kept apart mechanically by
        # SuperPolicy's fleet wide traffic pass.
        for report in self.defenders(snapshot, symptoms, flying):
            wanted[report.uav_id] = ("defend-base", {})

        # rule 1: a UAV one collision from destruction is taken out of traffic whatever else is going on
        for report in flying:
            if report.hp <= 1:
                wanted[report.uav_id] = ("disperse", self.disperse_params(report))

        return wanted

    # the UAVs to put on base defence: the ones closest to the base, as many as the threat calls for. UAVs
    # down to their last health point are not eligible, because rule 1 is about to take them out of traffic
    # anyway and picking one would leave the base a defender short.
    #
    # The detachment is re-picked from scratch every evaluation, and it is worth saying why, because the
    # churn that causes looks like a bug. The UAVs are moving, so which of them is nearest the base changes
    # from step to step, and the membership of the detachment changes with it: a UAV is wanted for defence,
    # then not, then wanted again. The obvious remedy is to prefer the UAVs already doing the job. It was
    # tried, and it is worse. Over 120 seeded runs on a 30x30 grid with 5 UAVs:
    #
    #     incumbency bonus   0 cells (this)      17/120 lost   268 base burn-steps   4746 adaptations
    #     incumbency bonus   1 cell              18/120 lost   283 base burn-steps   3831 adaptations
    #     incumbency bonus   2 cells             19/120 lost   276 base burn-steps   3240 adaptations
    #     incumbents always win                  22/120 lost   296 base burn-steps   2890 adaptations
    #
    # Every cell of incumbency buys a quieter log and costs bases. The churn is not waste: it is the
    # detachment tracking which UAV can actually reach the front first, and a UAV that has drifted off is
    # not the one to leave holding the job. Per UAV hysteresis still damps the genuine policy flips, which
    # is where the thrashing that matters would otherwise be.
    def defenders(self, snapshot, symptoms, flying):
        eligible = [report for report in flying if report.hp > 1]
        count = self.defender_count(symptoms, len(eligible))
        if not count or snapshot.base is None:
            return []

        # a UAV whose position was not reported cannot be ranked by distance, and goes last
        def distance(report):
            if report.pos is None:
                return float("inf")
            return snapshot.base.distance_to(report.pos)

        return sorted(eligible, key=distance)[:count]

    # how much of the team the base threat is worth. Level 3 means the base is alight or already lost, and
    # there is nothing else left worth doing.
    def defender_count(self, symptoms, flying):
        if not symptoms.base_threat or not flying:
            return 0
        if symptoms.base_threat >= 3:
            return flying
        share = self.THREAT_SHARES.get(symptoms.base_threat, 1 / 3)
        return max(1, math.ceil(flying * share))

    # how much room to ask for, and how slowly to take it. A UAV on its last health point is given a wider
    # berth than the rest of the team, because for that one a collision is not damage but destruction.
    def disperse_params(self, report):
        separation = math.ceil(config.SECURITY_DISTANCE) + (1 if report.hp <= 1 else 0)
        return {"separation": separation, "speed_cap": config.MANAGING_CROWDED_SPEED_CAP}

    # one line saying what was decided and why, which is logged, shown on the status panel and kept in the
    # Knowledge base. It is written from what was wanted rather than what was issued, so that it explains
    # the decision even on the evaluations where hysteresis held part of it back.
    def rationale(self, symptoms, wanted, issued, flying):
        counts = {}
        for policy_name, _ in wanted.values():
            counts[policy_name] = counts.get(policy_name, 0) + 1
        summary = ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))

        if symptoms.base_threat:
            distance = symptoms.threat_distance
            reason = (f"base threat {symptoms.base_threat}"
                      + (f" (fire {distance:.1f} cells off)" if distance != float("inf") else ""))
        elif symptoms.crowding:
            reason = f"{len(symptoms.crowding)} UAV(s) flying too close"
        elif symptoms.at_risk:
            reason = f"{len(symptoms.at_risk)} UAV(s) at risk"
        else:
            reason = "nothing wrong"

        held = flying - issued
        return f"{reason}: {summary}" + (f"; {held} held by hysteresis" if held else "")
