"""Everything the managing system and the managed system say to each other.

These are the only types that cross the boundary between the two. The managing system is shown a
FleetSnapshot and answers with an Allocation; it never sees a UAV, a grid, a mesa agent or the model. That
is what its independence amounts to in practice, and it is enforced two ways: nothing in sim/managing/
imports the simulation (tests/managing/test_independence.py checks it), and every type here is frozen, so
even the objects it is handed cannot be used to reach back and change anything.

They are also the wire format. Each one round trips through to_json()/from_json() without loss, which is
what lets the whole Plan step be moved to another process, another machine or another language without any
of the rest of the architecture changing. The round trip is tested, because that equality *is* the remote
contract: see sim/managing/plan/remote.py.

Positions are normalised to tuples of ints on construction, so that a snapshot built by hand in a test
compares equal to the same snapshot after a trip through JSON, where every tuple came back a list.
"""

# python libraries

from dataclasses import dataclass, field, replace


# --- normalisation helpers --------------------------------------------------


# one (x, y) cell as a tuple of ints, from a tuple, a list or anything else indexable
def _cell(value):
    if value is None:
        return None
    return (int(value[0]), int(value[1]))


# a sequence of cells as a tuple of tuples, which is what makes two snapshots built different ways
# compare equal
def _cells(value):
    return tuple(_cell(cell) for cell in (value or ()))


# a mapping keyed by UAV id. JSON has no integer keys, so a dictionary that has been through it comes
# back keyed by strings; this puts it back the way it went in.
def _by_uav(value):
    return {int(uav_id): count for uav_id, count in (value or {}).items()}


# --- what the managed system reports ----------------------------------------


@dataclass(frozen=True)
class UavReport:
    """What one UAV tells the managing system about itself and what it can see.

    Everything here is either the UAV's own state or something inside its own observation window, so the
    managing system is exactly as partially sighted as the team it is managing. It learns nothing about a
    part of the map no UAV is looking at, and a team that loses UAVs goes blind in the places they were.

    'policy' and 'params' are what this UAV is flying *right now*, which closes the MAPE-K loop: the
    managing system is told the effect of its own last decision, not just the state of the world, so it can
    tell an allocation that has taken hold from one it has just made.

    With the positioning error extension on, 'pos' and 'sees_uavs' are positions that were *measured* rather
    than true grid cells, so they can be several cells out and two UAVs can report the same one; 'sees_fire'
    and 'sees_buildings' are where the fire and the buildings really are.

    With smoke occlusion on, 'sees_occluded' names the cells of the window the smoke took away, and the three
    'sees_' lists above are silent about them: a burning cell under smoke is not in 'sees_fire', a team mate
    under smoke is not in 'sees_uavs', a building under smoke is not in 'sees_buildings'. It is the first
    field in this contract that reports an absence of knowledge rather than a piece of it, and the only way
    a planner can tell "this UAV looked there and saw nothing" from "this UAV looked there and saw nothing
    through the smoke".
    """

    uav_id: int
    pos: tuple = None
    alive: bool = True
    hp: int = 0
    water: int = 0
    policy: str = ""
    params: dict = field(default_factory=dict)
    # None when the fuel extension is switched off, exactly as in Observation, so that a planner can tell
    # "this UAV is dry" from "fuel is not being tracked in this run"
    fuel: float = None
    fuel_capacity: float = None
    # what this UAV can see: burning cells, other UAVs, and out buildings, all inside its own window
    sees_fire: tuple = ()
    sees_uavs: tuple = ()
    sees_buildings: tuple = ()
    # and what it could not: the cells of the window the smoke hid, empty when nothing is occluding
    sees_occluded: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "pos", _cell(self.pos))
        object.__setattr__(self, "sees_fire", _cells(self.sees_fire))
        object.__setattr__(self, "sees_uavs", _cells(self.sees_uavs))
        object.__setattr__(self, "sees_buildings", _cells(self.sees_buildings))
        object.__setattr__(self, "sees_occluded", _cells(self.sees_occluded))
        object.__setattr__(self, "params", dict(self.params or {}))

    # how much of a full tank is left, as a fraction. Reports a full tank when fuel is not being tracked,
    # so a planner that reads it plans the same way it would have before the extension existed.
    def fuel_fraction(self):
        if self.fuel is None or not self.fuel_capacity:
            return 1.0
        return max(0.0, min(1.0, self.fuel / self.fuel_capacity))

    # how many other UAVs this one can see
    def neighbours(self):
        return len(self.sees_uavs)

    # how many cells of its window the smoke took away, which is how blind this UAV is right now
    def blind_cells(self):
        return len(self.sees_occluded)

    def to_json(self):
        return {
            "uav_id": self.uav_id, "pos": list(self.pos) if self.pos else None,
            "alive": self.alive, "hp": self.hp, "water": self.water,
            "policy": self.policy, "params": dict(self.params),
            "fuel": self.fuel, "fuel_capacity": self.fuel_capacity,
            "sees_fire": [list(cell) for cell in self.sees_fire],
            "sees_uavs": [list(cell) for cell in self.sees_uavs],
            "sees_buildings": [list(cell) for cell in self.sees_buildings],
            "sees_occluded": [list(cell) for cell in self.sees_occluded],
        }

    @classmethod
    def from_json(cls, payload):
        return cls(
            uav_id=int(payload["uav_id"]), pos=payload.get("pos"),
            alive=bool(payload.get("alive", True)), hp=int(payload.get("hp", 0)),
            water=int(payload.get("water", 0)), policy=payload.get("policy", ""),
            params=payload.get("params") or {},
            fuel=payload.get("fuel"), fuel_capacity=payload.get("fuel_capacity"),
            sees_fire=payload.get("sees_fire"), sees_uavs=payload.get("sees_uavs"),
            sees_buildings=payload.get("sees_buildings"),
            sees_occluded=payload.get("sees_occluded"),
        )


@dataclass(frozen=True)
class BaseReport:
    """The state of the home base, and the fire around it.

    'fire_near_base' is the one thing in a snapshot that is not filtered through a UAV: the base is modelled
    as having a fire sensor of its own, covering BASE_SENSOR_RADIUS cells beyond its footprint. Without it
    the managing system could be blind to the fire walking into the very asset it exists to protect, simply
    because the team had flown off somewhere else -- and it would then have no reason to call them back.

    That sensor is a camera like any other, so smoke blinds it: 'occluded_near_base' names the cells within
    its radius that it could not read, and those cells are absent from 'fire_near_base' whatever is burning
    on them. A base whose own sensor has gone dark at the moment the fire arrives is the sharpest thing this
    contract can now say, and nearest_fire_distance() answering infinity is no longer proof that nothing is
    coming.
    """

    cells: tuple = ()
    burning_steps: int = 0
    bhp: int = 1
    destroyed: bool = False
    serving: int = 0
    fire_near_base: tuple = ()
    # cells inside the sensor's radius that the smoke hid, empty when nothing is occluding
    occluded_near_base: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "cells", _cells(self.cells))
        object.__setattr__(self, "fire_near_base", _cells(self.fire_near_base))
        object.__setattr__(self, "occluded_near_base", _cells(self.occluded_near_base))

    # the anchor cell, which is the one the Base agent itself stands on
    def anchor(self):
        return self.cells[0] if self.cells else None

    # how much of the damage the base can survive it has already taken, as a fraction
    def damage_fraction(self):
        if not self.bhp:
            return 0.0
        return max(0.0, min(1.0, self.burning_steps / self.bhp))

    # how far a cell is from the nearest cell of the footprint
    def distance_to(self, cell):
        if not self.cells:
            return float("inf")
        return min(((cell[0] - own[0]) ** 2 + (cell[1] - own[1]) ** 2) ** 0.5 for own in self.cells)

    # how far away the closest fire the base can see is, or infinity when it can see none
    def nearest_fire_distance(self):
        if not self.fire_near_base:
            return float("inf")
        return min(self.distance_to(cell) for cell in self.fire_near_base)

    def to_json(self):
        return {
            "cells": [list(cell) for cell in self.cells],
            "burning_steps": self.burning_steps, "bhp": self.bhp,
            "destroyed": self.destroyed, "serving": self.serving,
            "fire_near_base": [list(cell) for cell in self.fire_near_base],
            "occluded_near_base": [list(cell) for cell in self.occluded_near_base],
        }

    @classmethod
    def from_json(cls, payload):
        if payload is None:
            return None
        return cls(
            cells=payload.get("cells"), burning_steps=int(payload.get("burning_steps", 0)),
            bhp=int(payload.get("bhp", 1)), destroyed=bool(payload.get("destroyed", False)),
            serving=int(payload.get("serving", 0)), fire_near_base=payload.get("fire_near_base"),
            occluded_near_base=payload.get("occluded_near_base"),
        )


@dataclass(frozen=True)
class FleetSnapshot:
    """One reading of the managed system, taken through the sensor.

    This is the whole of what the managing system is ever told. 'base' is None when the firefighting
    extension is switched off, in which case there is no base to defend and a planner has only the
    collision goal to work with.
    """

    step: int = 0
    grid_size: tuple = None
    uavs: tuple = ()
    base: BaseReport = None

    def __post_init__(self):
        object.__setattr__(self, "grid_size", _cell(self.grid_size))
        object.__setattr__(self, "uavs", tuple(self.uavs or ()))

    # the UAVs still flying, which are the only ones worth allocating anything to
    def alive(self):
        return tuple(report for report in self.uavs if report.alive)

    # one UAV's report, or None for an id that is not in this snapshot
    def by_id(self, uav_id):
        for report in self.uavs:
            if report.uav_id == uav_id:
                return report
        return None

    # every burning cell anybody can see, the base sensor included, without duplicates.
    #
    # Note what its complement means once smoke can occlude. A cell outside this set used to be one that was
    # either not burning or that nobody was looking at; it can now also be one that somebody looked straight
    # at and could not see through. known_blind() below is what separates the third case from the second.
    def known_fire(self):
        cells = set()
        for report in self.uavs:
            cells.update(report.sees_fire)
        if self.base is not None:
            cells.update(self.base.fire_near_base)
        return cells

    # every cell somebody looked at and learned nothing about, without duplicates. Nothing in sim/managing/
    # reads this yet, on purpose: what a managing system should do about being blind -- send a UAV round the
    # plume, call the team home to a base whose sensor has gone dark, stop counting on a report that is
    # mostly smoke -- is a design question that deserves its own change and its own evidence, and merging it
    # with the occlusion itself would make neither attributable in a sweep.
    def known_blind(self):
        cells = set()
        for report in self.uavs:
            cells.update(report.sees_occluded)
        if self.base is not None:
            cells.update(self.base.occluded_near_base)
        return cells

    def to_json(self):
        return {
            "step": self.step,
            "grid_size": list(self.grid_size) if self.grid_size else None,
            "uavs": [report.to_json() for report in self.uavs],
            "base": self.base.to_json() if self.base is not None else None,
        }

    @classmethod
    def from_json(cls, payload):
        return cls(
            step=int(payload.get("step", 0)),
            grid_size=payload.get("grid_size"),
            uavs=tuple(UavReport.from_json(report) for report in payload.get("uavs") or ()),
            base=BaseReport.from_json(payload.get("base")),
        )


# --- what the analyser makes of it ------------------------------------------


@dataclass(frozen=True)
class Symptoms:
    """What the Analyse step concluded from a snapshot.

    Kept separate from the snapshot because it is a judgement rather than an observation, and separate from
    the plan because more than one planner reads it. It goes on the wire alongside the snapshot, so that a
    remote planner may either use this reading or ignore it and analyse the raw snapshot itself.
    """

    # 0 nothing, 1 fire in the area, 2 fire closing, 3 the base is alight or nearly lost
    base_threat: int = 0
    # how far the nearest fire the base knows about is, in cells
    threat_distance: float = float("inf")
    # uav id -> how many team mates it can see closer than SECURITY_DISTANCE
    crowding: dict = field(default_factory=dict)
    # uav ids that are low on health points or nearly dry, and are worth preserving rather than spending
    at_risk: tuple = ()
    # UAVs that have already been lost, of the team that started
    lost: int = 0
    flying: int = 0

    def __post_init__(self):
        object.__setattr__(self, "crowding", _by_uav(self.crowding))
        object.__setattr__(self, "at_risk", tuple(int(uav_id) for uav_id in self.at_risk or ()))

    # whether any of this is worth re-planning for. A quiet step short circuits the loop before Plan, which
    # is what keeps the cost of a managing system that runs every step down -- and, with the remote
    # planner, is the difference between one request per step and one request per event.
    def requires_adaptation(self):
        return bool(self.base_threat or self.crowding or self.at_risk)

    # the UAVs that are crowded, worst first
    def crowded_uavs(self):
        return [uav_id for uav_id, _ in sorted(self.crowding.items(), key=lambda item: -item[1])]

    def to_json(self):
        return {
            "base_threat": self.base_threat,
            # infinity is not valid JSON, so an unthreatened base reports None over the wire
            "threat_distance": None if self.threat_distance == float("inf") else self.threat_distance,
            "crowding": {str(uav_id): count for uav_id, count in self.crowding.items()},
            "at_risk": list(self.at_risk), "lost": self.lost, "flying": self.flying,
        }

    @classmethod
    def from_json(cls, payload):
        distance = payload.get("threat_distance")
        return cls(
            base_threat=int(payload.get("base_threat", 0)),
            threat_distance=float("inf") if distance is None else float(distance),
            crowding=payload.get("crowding") or {},
            at_risk=payload.get("at_risk") or (),
            lost=int(payload.get("lost", 0)), flying=int(payload.get("flying", 0)),
        )


# --- what the managing system asks for --------------------------------------


@dataclass(frozen=True)
class UavDirective:
    """One UAV's orders: the policy it is to fly, and the settings to fly it under.

    'params' is a plain dictionary rather than a PolicyParams, because PolicyParams belongs to the managed
    system and importing it here would be exactly the dependency this package exists without. The effector
    turns it into one, and rejects anything it does not recognise.
    """

    uav_id: int
    policy: str
    params: dict = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "params", dict(self.params or {}))

    def to_json(self):
        return {"uav_id": self.uav_id, "policy": self.policy, "params": dict(self.params)}

    @classmethod
    def from_json(cls, payload):
        return cls(uav_id=int(payload["uav_id"]), policy=str(payload["policy"]),
                   params=payload.get("params") or {})


@dataclass(frozen=True)
class Allocation:
    """The whole team's orders for the steps until the next adaptation.

    'rationale' is why, in one line. It costs nothing to carry and is what makes the managing system's
    behaviour readable: it is logged, shown on the status panel and kept in the Knowledge base, so a run
    can be read back as a sequence of decisions and reasons rather than a sequence of policy changes with
    no explanation attached.
    """

    step: int = 0
    directives: tuple = ()
    rationale: str = ""

    def __post_init__(self):
        object.__setattr__(self, "directives", tuple(self.directives or ()))

    # the directive for one UAV, or None when the plan says nothing about it
    def for_uav(self, uav_id):
        for directive in self.directives:
            if directive.uav_id == uav_id:
                return directive
        return None

    # how many UAVs are to fly each policy, which is what the log and the status panel summarise
    def counts(self):
        counts = {}
        for directive in self.directives:
            counts[directive.policy] = counts.get(directive.policy, 0) + 1
        return counts

    # the same allocation with a different rationale, used by a planner that adopts another one's decision
    def because(self, rationale):
        return replace(self, rationale=rationale)

    def to_json(self):
        return {"step": self.step, "rationale": self.rationale,
                "directives": [directive.to_json() for directive in self.directives]}

    @classmethod
    def from_json(cls, payload):
        return cls(
            step=int(payload.get("step", 0)),
            directives=tuple(UavDirective.from_json(directive)
                             for directive in payload.get("directives") or ()),
            rationale=payload.get("rationale", ""),
        )

    def __str__(self):
        summary = ", ".join(f"{count}x{name}" for name, count in sorted(self.counts().items()))
        return f"{summary or 'nothing'} ({self.rationale})" if self.rationale else summary or "nothing"
