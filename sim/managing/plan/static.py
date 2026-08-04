"""A planner that decides once and then leaves the team alone."""

# own python modules

from ..contract import Allocation, UavDirective
from .base import Planner


class StaticPlanner(Planner):
    """Allocates a policy once and never reconsiders it. The experimental control.

    This is not a placeholder. Measuring what the managing system is worth means comparing it against the
    simulation without one, and until now that comparison confounded two separate changes: turning the
    managing system on also puts the team on a SuperPolicy, which dispatches per UAV *and* trims every
    action against the rest of the fleet whatever policy a UAV is flying. So an unmanaged run and a managed
    run differ in whether policies are reallocated **and** in whether there is fleet wide collision
    avoidance at all, and a difference in the results cannot be attributed to either.

    A managing system built around this planner is the missing middle arm. It runs the whole loop -- reads
    the sensor, analyses, plans, executes -- and plans no change, so the team flies under SuperPolicy
    without ever being reallocated:

        --managing none       no SuperPolicy,  no adaptation      what the simulation does on its own
        --managing static     SuperPolicy,     no adaptation      what SuperPolicy alone is worth
        --managing heuristic  SuperPolicy,     adaptation         what the managing system is worth

    By default it restates what each UAV is already flying, which is whatever the run was started under, so
    the arm is a like-for-like control of the unmanaged one whatever --policy was passed. Naming a policy
    instead holds the whole team on that one for the run.
    """

    name = "static"

    # constructor. 'policy' names what everybody flies; None keeps each UAV on whatever it already had.
    def __init__(self, policy=None):
        self.policy = policy
        # the allocation is issued once and not restated, so that the run's adaptation count says what it
        # should -- one decision, taken at the start, never revised
        self.issued = False

    def plan(self, snapshot, symptoms=None, knowledge=None):
        flying = snapshot.alive()

        if self.issued or not flying:
            return Allocation(step=snapshot.step, rationale="static allocation, nothing to change")

        directives = tuple(
            UavDirective(uav_id=report.uav_id,
                         policy=self.policy if self.policy is not None else report.policy,
                         params={})
            for report in flying if self.policy is not None or report.policy
        )
        self.issued = bool(directives)

        return Allocation(step=snapshot.step, directives=directives,
                          rationale=f"static allocation: {len(directives)} UAV(s) held on "
                                    f"{self.policy or 'what they started under'} for the run")
