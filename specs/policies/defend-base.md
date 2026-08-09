# `defend-base` — intercept the fire that threatens the base

`firefighter` sends each UAV at whatever is burning closest to it. That is the right call when the job is
putting the wildfire out, and the wrong one when the job is keeping one building standing: a team spread over
the map fights whatever it happens to be standing over while the front that matters walks into the base.

This policy orders the fire it can see by how close it is **to the base**, so a UAV holding station over the
base and a UAV out on the perimeter converge on the same front from wherever they are.

Inherited obligations: see [`_contract.md`](_contract.md).

The refuelling and refilling rungs are the same ones `firefighter` has, and are specified again here rather
than cross-referenced: the two policies are independent, and a change to one is not a change to the other.
Where the behaviour is genuinely shared code, `satisfied_by` says so.

## POL-DEF-1 — The target is the fire nearest the base, not the nearest fire

> The policy SHALL select as a UAV's target the burning position closest to `observation.base_footprint()`,
> not the one closest to `observation.pos`.

It is the whole difference between this policy and firefighter. Ordering by distance to the base is what makes
a scattered team converge on one front instead of each UAV picking off what is under it.

**Assumptions:**

- `config.ACTIVATE_FIREFIGHTING` is true. Without a base there is nothing to defend; see POL-DEF-8.

```yaml
id: POL-DEF-1
satisfied_by:
  - sim/policy/defend_base.py::DefendBasePolicy.pick_target
  - sim/policy/defend_base.py::DefendBasePolicy.distance_to_base
verified_by: test
status: agreed
```

## POL-DEF-2 — Fire too far from the base is not this policy's problem

> The policy SHALL NOT select a burning position further than `config.BASE_THREAT_RADIUS` from
> `observation.base_footprint()`, even when it is the only fire in view.

A UAV that flew at every fire it could see would be firefighter with extra steps. The radius is what makes the
policy hold its UAVs near the base instead of being drawn away by a front that will never reach it.

```yaml
id: POL-DEF-2
satisfied_by:
  - sim/policy/defend_base.py::DefendBasePolicy.pick_target
verified_by: test
status: agreed
```

## POL-DEF-3 — Water is dumped once the threatening fire is in range

> When the UAV carries water and the selected target is within `config.WATER_DROP_RADIUS` of
> `observation.pos`, the policy SHALL return `Action.dump()`; otherwise it SHALL fly the UAV toward that
> target.

Same reasoning as the firefighting policy: a drop from out of range does nothing, and flying closer once in
range wastes a step.

```yaml
id: POL-DEF-3
satisfied_by:
  - sim/policy/defend_base.py::DefendBasePolicy.action_for
  - sim/policy/defend_base.py::DefendBasePolicy.within_drop_range
verified_by: test
status: agreed
```

## POL-DEF-4 — With nothing threatening the base, the UAV holds station over it

> When no burning position in view is within `config.BASE_THREAT_RADIUS` of the base, the policy SHALL fly
> the UAV toward `observation.base_footprint()`, and SHALL return `Action.stay()` once
> `observation.at_base()` is true.

Waiting on the base rather than wandering puts the UAV where it needs to be when the front arrives. The base
is shared airspace, so a whole team can wait there without colliding, which means this policy costs nothing in
collisions and the managing system can allocate it freely.

```yaml
id: POL-DEF-4
satisfied_by:
  - sim/policy/defend_base.py::DefendBasePolicy.hold_at_base
  - sim/policy/defend_base.py::DefendBasePolicy.base_anchor
verified_by: test
status: agreed
```

## POL-DEF-5 — A UAV without water goes back to the base

> When `observation.has_water` is false, the policy SHALL fly the UAV toward the base and SHALL NOT select a
> fire as its target.

An empty UAV cannot defend anything, and the base is both where it refills and where it should be waiting
anyway.

```yaml
id: POL-DEF-5
satisfied_by:
  - sim/policy/defend_base.py::DefendBasePolicy.action_for
verified_by: test
status: agreed
```

## POL-DEF-6 — The fuel reserve outranks the defending

> When `observation.low_fuel()` is true, the policy SHALL fly the UAV toward the base and SHALL NOT select a
> fire as its target, whatever water it carries and whatever threatens the base.

The same trade as in firefighter: a UAV that would not survive the trip is worth more to the run intact and
idle than dry and destroyed. Losing the airframe also loses the base its defender for the rest of the run,
which is the thing this policy exists to prevent.

**Assumptions:**

- `config.ACTIVATE_FUEL` is true. With the extension off, `low_fuel()` is never true and this rung never
  fires.

```yaml
id: POL-DEF-6
satisfied_by:
  - sim/policy/defend_base.py::DefendBasePolicy.action_for
  - sim/policy/observation.py::Observation.low_fuel
verified_by: test
status: agreed
```

## POL-DEF-7 — A UAV on the base waits there to be served

> When the UAV is on the base and is either empty of water or below the fuel reserve, the policy SHALL
> return `Action.stay()` until the condition is no longer reported.

Refilling and refuelling take `BASE_REFILL_STEPS` and `BASE_REFUEL_STEPS` with the base serving one UAV at a
time. Leaving the moment it landed would mean never being served at all.

```yaml
id: POL-DEF-7
satisfied_by:
  - sim/policy/defend_base.py::DefendBasePolicy.hold_at_base
verified_by: test
status: agreed
```

## POL-DEF-8 — With no base, there is nothing to defend

> When `observation.base_footprint()` is empty, the policy SHALL select no target and SHALL return
> `Action.stay()`.

This is what selecting the policy with the firefighting extension switched off looks like. Both
`--policy defend-base` and the web interface dropdown allow it, so it has to be survivable rather than an
error.

```yaml
id: POL-DEF-8
satisfied_by:
  - sim/policy/defend_base.py::DefendBasePolicy.base_anchor
  - sim/policy/defend_base.py::DefendBasePolicy.pick_target
verified_by: test
status: agreed
```

## POL-DEF-9 — No two UAVs are sent to the same fire in one step

> When a burning position has already been given to a UAV earlier in the same call, the policy SHALL select
> the next closest position to the base instead.

Two loads on one cell buy nothing, and send two UAVs at the same piece of airspace. Claiming targets in team
order spreads the fleet along the front nearest the base.

Unlike `firefighter`, this policy does no flight trimming of its own: `SuperPolicy` deconflicts the whole
fleet afterwards. Claimed targets are still tracked so the policy is correct when it is flown on its own
through `--policy defend-base`.

```yaml
id: POL-DEF-9
satisfied_by:
  - sim/policy/defend_base.py::DefendBasePolicy.select_actions
  - sim/policy/defend_base.py::DefendBasePolicy.pick_target
verified_by: test
status: agreed
```

## POL-DEF-10 — The rules are applied in order

> The policy SHALL apply its rules in the order fuel reserve (POL-DEF-6), then water (POL-DEF-5), then the
> fire nearest the base (POL-DEF-1), then holding station (POL-DEF-4), selecting the action of the first
> rule whose condition holds and ignoring the rest.

The rungs conflict: a UAV low on fuel, carrying water, with the base under threat satisfies three at once. The
ordering decides, and testing each rung on its own cannot tell whether the ordering survived a change.

```yaml
id: POL-DEF-10
satisfied_by:
  - sim/policy/defend_base.py::DefendBasePolicy.action_for
verified_by: test
status: agreed
```
