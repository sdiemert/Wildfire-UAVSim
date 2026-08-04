"""Per UAV settings that come with a policy assignment.

A UAV is allocated a policy *and* a set of parameters to fly it under, so that two UAVs on the same policy
can still be flown differently: one held to a crawl because it is boxed in by its team mates, another given
its head over open ground. The managing system produces these; the managed system enforces them.

The two that every policy obeys, `speed_cap` and `separation`, are applied by SuperPolicy after the policy
has chosen, so they hold whatever the policy asked for. Anything a particular policy understands and no
other one does goes in `extra`, and reaches the policy through Policy.configure().
"""

# python libraries

from dataclasses import dataclass, field

# own python modules

# see the note in random_policy.py about importing config as a module
import config


@dataclass(frozen=True)
class PolicyParams:
    """How one UAV is to fly the policy it has been allocated.

    'speed_cap' is the most cells the UAV may cover in a step, on top of the UAV_SPEED limit the simulation
    imposes anyway. None leaves it at UAV_SPEED.

    'separation' is how far the UAV is to stay from the team mates it can see, in cells. Zero means only the
    cells they are standing on are kept clear, which is the least that stops a collision; a larger value
    keeps a cushion around each of them, at the cost of the UAV giving up speed to do it.

    'fuel_reserve' overrides UAV_FUEL_RESERVE for this UAV alone, so that one flown far from the base can be
    told to turn for home earlier than the rest of the team. None leaves it at the configured value.

    'extra' is whatever a single policy understands and the others do not. It is handed over by
    Policy.configure() and ignored by every policy that does not look for it.
    """

    speed_cap: int = None
    separation: int = 0
    fuel_reserve: float = None
    extra: dict = field(default_factory=dict)

    # the speed this UAV may actually fly at, which is the lower of its cap and what a UAV can do at all
    def effective_speed(self):
        if self.speed_cap is None:
            return config.UAV_SPEED
        return max(0, min(int(self.speed_cap), config.UAV_SPEED))

    # the reserve this UAV turns for home on, falling back to the configured one. Read at call time, so
    # overriding UAV_FUEL_RESERVE for a run still reaches every UAV that was not given one of its own.
    def effective_reserve(self):
        return config.UAV_FUEL_RESERVE if self.fuel_reserve is None else float(self.fuel_reserve)

    # a hashable form of these parameters, which is what lets SuperPolicy group the UAVs flying under
    # identical settings and hand them to one policy call. Dictionaries are not hashable, so 'extra' is
    # flattened into a sorted tuple of pairs.
    def key(self):
        return (self.speed_cap, self.separation, self.fuel_reserve,
                tuple(sorted((name, str(value)) for name, value in self.extra.items())))

    # the plain dictionary that crosses the wire to and from the managing system
    def to_json(self):
        return {"speed_cap": self.speed_cap, "separation": self.separation,
                "fuel_reserve": self.fuel_reserve, "extra": dict(self.extra)}

    # builds parameters from what a planner sent, ignoring keys it invented. A planner that sends nothing
    # at all gets the defaults, which is the same as not being flown to any particular setting.
    @classmethod
    def from_json(cls, payload):
        if payload is None:
            return cls()
        if isinstance(payload, cls):
            return payload
        return cls(
            speed_cap=payload.get("speed_cap"),
            separation=int(payload.get("separation") or 0),
            fuel_reserve=payload.get("fuel_reserve"),
            extra=dict(payload.get("extra") or {}),
        )

    def __str__(self):
        parts = []
        if self.speed_cap is not None:
            parts.append(f"speed<={self.speed_cap}")
        if self.separation:
            parts.append(f"separation={self.separation}")
        if self.fuel_reserve is not None:
            parts.append(f"reserve={self.fuel_reserve}")
        return ", ".join(parts) if parts else "defaults"
