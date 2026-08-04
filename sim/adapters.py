"""The sensors and effectors that join the managing system to the simulation.

This is the only module in the project that imports both halves. Everything above it -- sim/managing/ --
knows the simulation exists solely as the two interfaces in sim/managing/ports.py; everything below it --
the model, the agents, the policies -- does not know a managing system exists at all. Putting the two
adapters here, rather than inside either half, is what lets both of those be true at once.

  ModelSensor          reads  WildFireModel + SuperPolicy -> FleetSnapshot
  AllocationEffector   writes Allocation -> SuperPolicy

Neither direction is a shortcut for the other. The sensor builds frozen messages rather than handing model
objects over, so the managing system cannot follow a reference back into the simulation; the effector
validates everything it is given, so the simulation is not at the mercy of whatever planned it.
"""

# python libraries

import logging

# own python modules

import config

from sim.managing.contract import BaseReport, FleetSnapshot, UavReport
from sim.managing.ports import Effector, Sensor
from sim.policy import POLICIES, PolicyParams


class ModelSensor(Sensor):
    """Reports the managed system as a FleetSnapshot.

    What it chooses to report is the observability of the whole managing system, so it is worth being
    explicit about it. Two sources, and no others:

      * **the UAVs.** Each one is asked what it can see, through the same UAV.observe() the policies are
        given, so the managing system is exactly as partially sighted as the team it manages. It learns
        nothing about a corner of the map nobody is looking at, and a team that loses UAVs goes blind
        where they were. Each UAV also reports its own state, and the policy it is flying right now --
        which is what closes the loop, because it lets the managing system see the effect of its own last
        decision rather than only the state of the world.

      * **the home base.** Modelled as having a fire sensor of its own, covering BASE_SENSOR_RADIUS cells
        beyond its footprint, and reported whether or not any UAV is nearby. This is the one thing that is
        not filtered through the team, and it is there because the alternative is perverse: a managing
        system whose job is to keep the base standing, which cannot see the base burning because the team
        it sent away is the only thing that could have told it.

    The cost is one extra observe() per live UAV per reading. ADAPTATION_PERIOD is what that is traded
    against; the cells the base sensor covers are worked out once and cached, because the base does not
    move.
    """

    # constructor. 'model' is the WildFireModel being managed and 'super_policy' the SuperPolicy it is
    # flying, which is where the currently active allocation is read from.
    def __init__(self, model, super_policy):
        self.model = model
        self.super_policy = super_policy
        # (base object, cells) -- the footprint does not move, so the cells its sensor covers are worked
        # out once. Keyed on the base itself so that a model rebuilt in place gets a fresh cache.
        self._sensed_cells = (None, ())

    def read(self):
        return FleetSnapshot(
            step=self.model.evaluation_timesteps_counter,
            grid_size=(config.HEIGHT, config.WIDTH),
            uavs=tuple(self.uav_report(uav) for uav in self.model.uavs),
            base=self.base_report(),
        )

    # one UAV's entry. A destroyed UAV has been taken off the grid, so it has no position and nothing to
    # see; it is still reported, because attrition is something the managing system needs to know about.
    def uav_report(self, uav):
        policy_name, params = self.super_policy.allocated(uav.unique_id)

        if not uav.is_alive() or uav.pos is None:
            return UavReport(uav_id=uav.unique_id, pos=None, alive=False, hp=max(0, uav.hp),
                             water=uav.water, policy=policy_name, params=params.to_json())

        observation = uav.observe()
        return UavReport(
            uav_id=uav.unique_id,
            pos=uav.pos,
            alive=True,
            hp=uav.hp,
            water=uav.water,
            policy=policy_name,
            params=params.to_json(),
            fuel=observation.fuel,
            fuel_capacity=observation.fuel_capacity,
            sees_fire=observation.burning_positions(),
            sees_uavs=observation.uav_positions,
            sees_buildings=observation.building_positions,
        )

    # the home base and the fire around it, or None when the firefighting extension is switched off and
    # there is no base to defend
    def base_report(self):
        base = self.model.base
        if base is None:
            return None

        return BaseReport(
            cells=base.cells,
            burning_steps=base.burning_steps,
            bhp=config.BHP,
            destroyed=base.is_destroyed(),
            serving=len(base.serving),
            fire_near_base=self.fire_near_base(),
        )

    # the burning cells the base's own sensor can see
    def fire_near_base(self):
        burning = []
        for cell in self.sensed_cells():
            fire = self.model.fire_agent_at(cell)
            if fire is not None and fire.is_burning():
                burning.append(cell)
        return burning

    # every cell within BASE_SENSOR_RADIUS of the footprint, worked out once per base. The footprint itself
    # is included: fire on the base is the whole reason the sensor exists.
    def sensed_cells(self):
        base = self.model.base
        if self._sensed_cells[0] is base:
            return self._sensed_cells[1]

        cells = set()
        for cell in base.cells:
            cells.add(cell)
            cells.update(self.model.grid.get_neighborhood(
                cell, moore=True, include_center=True, radius=config.BASE_SENSOR_RADIUS))

        self._sensed_cells = (base, tuple(sorted(cells)))
        return self._sensed_cells[1]


class AllocationEffector(Effector):
    """Applies an Allocation by writing into the SuperPolicy's table.

    This is a trust boundary, not just a channel. What arrives may have been planned by a server on the
    other side of a network (see sim/managing/plan/remote.py), so nothing in it is believed: every
    directive is checked against the simulation that has to carry it out, and one that fails is dropped and
    logged rather than raised.

    Dropping rather than raising is the important part. A managing system that has gone wrong -- a planner
    with a bug, a server answering for a different run, a policy name that was renamed on one side and not
    the other -- should cost the run its adaptation quality, not end it. The team keeps flying whatever it
    was flying, the run finishes, and the log says exactly what was refused and why.

    Four things are checked: that the UAV exists, that it is still flying, that the policy is one the
    simulation has registered, and that the parameters are within their bounds.
    """

    # constructor
    def __init__(self, super_policy, model, log=None):
        self.super_policy = super_policy
        self.model = model
        self.log = log if log is not None else logging.getLogger("wildfire.managing")
        # how many directives have been refused over the run, reported at the end so that a result is
        # never read without knowing whether the managing system was actually being obeyed
        self.rejected = 0

    def apply(self, allocation):
        applied = 0
        for directive in allocation.directives:
            params = self.validate(directive)
            if params is None:
                continue
            self.super_policy.assign(directive.uav_id, directive.policy, params)
            applied += 1
        return applied

    # checks one directive over, returning the PolicyParams to apply it with, or None when it must be
    # refused. Every refusal is logged against the directive that caused it.
    def validate(self, directive):
        uav = self.model.uav_by_id(directive.uav_id)
        if uav is None:
            return self.refuse(directive, "no such UAV")
        if not uav.is_alive():
            return self.refuse(directive, "UAV has been destroyed")
        if directive.policy not in POLICIES:
            return self.refuse(directive, f"unknown policy, available: {', '.join(sorted(POLICIES))}")

        try:
            params = PolicyParams.from_json(directive.params)
        except (TypeError, ValueError) as exc:
            return self.refuse(directive, f"malformed parameters: {exc}")

        return self.validate_params(directive, params)

    # checks the parameters are ones a UAV can actually be flown to
    def validate_params(self, directive, params):
        if params.speed_cap is not None and (not isinstance(params.speed_cap, int) or params.speed_cap < 0):
            return self.refuse(directive, f"speed_cap must be an integer >= 0, got {params.speed_cap!r}")
        if params.separation < 0:
            return self.refuse(directive, f"separation must be >= 0, got {params.separation!r}")
        if params.fuel_reserve is not None and not 0.0 <= params.fuel_reserve <= 1.0:
            return self.refuse(directive, f"fuel_reserve must be in [0, 1], got {params.fuel_reserve!r}")
        return params

    # records a refused directive and answers None, which is what tells apply() to skip it
    def refuse(self, directive, reason):
        self.rejected += 1
        self.log.warning("refused directive for UAV %s (%s): %s",
                         directive.uav_id, directive.policy, reason)
        return None
