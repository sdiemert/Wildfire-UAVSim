# `firefighter` — carry water to the fire, refill at the base

The policy of the firefighting extension, and the default one a UAV flies under
(`config.DEFAULT_UAV_POLICY`). Each UAV runs an ordered ladder of rules — fuel, then water, then what to
attack — and the team is kept apart by two further rules that need the whole fleet at once.

The ladder is the part of this policy most easily broken by a change, and the part that testing each rung in
isolation cannot catch, so the ordering is a requirement of its own: **POL-FF-14**.

Inherited obligations: see [`_contract.md`](_contract.md).

## POL-FF-1 — The fuel reserve outranks everything else

The first rung of the ladder, checked before the water the UAV carries and before anything burning in view.

> When `observation.low_fuel()` is true, the policy SHALL fly the UAV toward `observation.base_pos` and
> SHALL NOT select a fire as its target, whatever water it carries and whatever is burning in view.

A UAV that runs dry loses every health point it has. Losing the airframe costs the rest of the run more than
the one water drop that pressing on would have delivered.

**Assumptions:**

- `config.ACTIVATE_FUEL` is true. With the extension off, `observation.low_fuel()` is never true and this rung
  of the ladder never fires, which is what lets the policy predate the fuel extension unchanged.
- `config.UAV_FUEL_RESERVE` is a flat share of the tank rather than an estimate of the fuel needed to reach
  the base, so a UAV that has strayed far enough can still run dry on the way home. Sizing the reserve against
  how far a run lets the team range is left to whoever configures it.

```yaml
id: POL-FF-1
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.action_for
  - sim/policy/observation.py::Observation.low_fuel
verified_by: test
status: agreed
```

## POL-FF-2 — A UAV without water goes back to the base

> When `observation.has_water` is false, the policy SHALL fly the UAV toward `observation.base_pos` and
> SHALL NOT select a fire as its target.

There is nothing an empty UAV can do to a fire. Refilling is the only move that returns it to being useful.

**Assumptions:**

- `config.ACTIVATE_FIREFIGHTING` is true. With it off no UAV ever carries water, and the policy degenerates to
  flying to the base and holding position there.

```yaml
id: POL-FF-2
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.action_for
  - sim/policy/firefighter.py::FirefighterPolicy.return_to_base
verified_by: test
status: agreed
```

## POL-FF-3 — A UAV at the base waits there to be served

> When the UAV is returning to the base and `observation.at_base()` is true, the policy SHALL return
> `Action.stay()` until the condition that sent it home is no longer reported.

Refilling and refuelling are not actions: standing on the base is what triggers them, and the base serves one
UAV at a time over `BASE_REFILL_STEPS` and `BASE_REFUEL_STEPS`. A UAV that left the moment it landed would
never stay long enough to be served, and would fly off exactly as empty as it arrived.

```yaml
id: POL-FF-3
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.return_to_base
  - sim/policy/observation.py::Observation.at_base
verified_by: test
status: agreed
```

## POL-FF-4 — With no base to return to, the UAV holds position

> When the UAV would return to the base but `observation.base_pos` is `None`, the policy SHALL return
> `Action.stay()`.

This is what the policy being selected with the firefighting extension switched off looks like. It has to be
survivable rather than an error, because `--policy firefighter` and the web interface dropdown both allow the
combination.

```yaml
id: POL-FF-4
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.return_to_base
verified_by: test
status: agreed
```

## POL-FF-5 — Water is dumped once the target is in range

> When the UAV carries water and the selected target is within `config.WATER_DROP_RADIUS` of
> `observation.pos`, the policy SHALL return `Action.dump()`.

The drop reaches the target from here, so flying closer wastes a step and risks the UAV ending it over a
burning cell.

The range is inclusive: a target exactly `WATER_DROP_RADIUS` away is in range.

```yaml
id: POL-FF-5
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.action_for
  - sim/policy/firefighter.py::FirefighterPolicy.within_drop_range
verified_by: test
status: agreed
```

## POL-FF-6 — Out of range, the UAV closes on the target

> When the UAV carries water and the selected target is further than `config.WATER_DROP_RADIUS` from
> `observation.pos`, the policy SHALL fly the UAV toward that target.

A drop from out of range does nothing. Closing the distance is the only way to make the load count.

```yaml
id: POL-FF-6
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.action_for
  - sim/policy/base.py::step_towards
verified_by: test
status: agreed
```

## POL-FF-7 — The target is the nearest unclaimed fire

> The policy SHALL select as a UAV's target the burning position closest to `observation.pos` that no UAV
> earlier in the same call has already been given.

Nearest is the cheapest fire for this UAV to reach. Skipping the ones already taken is what stops two UAVs
converging on one cell, which would waste a load and put them on a collision course.

```yaml
id: POL-FF-7
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.pick_target
  - sim/policy/base.py::by_distance
verified_by: test
status: agreed
```

## POL-FF-8 — Fire threatening an out building is attacked first

> When a burning position in view is within `config.WATER_DROP_RADIUS` of a position in
> `observation.building_positions`, the policy SHALL select it in preference to any burning position that is
> not, even when the latter is closer to the UAV.

An out building that burns is gone for the rest of the run, while open vegetation that burns is part of what
the run is measuring. The two are not worth the same load of water.

A building in view with no fire near it is not threatened, and does not pull a UAV off the nearest fire.

**Assumptions:**

- `config.NUM_OUT_BUILDINGS` is greater than zero. With no buildings on the grid,
  `observation.building_positions` is always empty and this rung never fires.

```yaml
id: POL-FF-8
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.pick_target
  - sim/policy/firefighter.py::FirefighterPolicy.threatened_fires
verified_by: test
status: agreed
```

## POL-FF-9 — Nothing left to attack means hold position

> When the UAV carries water and every burning position in view has already been given to a UAV earlier in
> the same call, or none is in view at all, the policy SHALL return `Action.stay()`.

Flying at a fire a teammate is already handling would waste the load and put two UAVs over one cell. Holding
position keeps the UAV loaded and in place for the next step.

```yaml
id: POL-FF-9
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.action_for
verified_by: test
status: agreed
```

## POL-FF-10 — No two UAVs are sent to the same fire in one step

> Within a single call to `select_actions()`, the policy SHALL NOT select the same burning position as the
> target for two UAVs.

Two loads on one cell put it out no better than one, and the second UAV has to fly to a cell the first is
already heading for. Claiming targets in team order is what keeps the fleet spread over the fire.

```yaml
id: POL-FF-10
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.select_actions
verified_by: test
status: agreed
```

## POL-FF-11 — A flight is trimmed to stop short of another UAV

> The policy SHALL reduce the speed of a movement action so that its flight path contains no position in
> `observation.uav_positions` and no position already on the flight path of a UAV earlier in the same call,
> returning `Action.stay()` when even the first cell is taken.

Two UAVs that end a step on the same cell collide and both roll for damage. Giving up a cell or two of speed
costs a fraction of a step; a collision costs health points that do not come back.

A UAV standing beside the route rather than on it costs nothing: only cells actually crossed are trimmed
against.

```yaml
id: POL-FF-11
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.deconflict
  - sim/policy/base.py::avoid
  - sim/policy/base.py::flight_path
verified_by: test
status: agreed
```

## POL-FF-12 — The home base is shared airspace

> The policy SHALL NOT trim a flight on account of a UAV standing on a position in
> `observation.base_footprint()`.

UAVs do not collide on the base, which is what lets them queue there to be served one at a time. A policy that
avoided the base as it avoids everything else would leave a UAV circling its own base and never refilling.

```yaml
id: POL-FF-12
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.deconflict
  - sim/policy/observation.py::Observation.base_footprint
verified_by: test
status: agreed
```

## POL-FF-13 — No UAV is sent further than it can see

> The policy SHALL reduce the speed of a movement action to at most `config.UAV_OBSERVATION_RADIUS`,
> returning `Action.stay()` when that radius is zero.

A flight that ends outside the observation window lands on a cell `observation.uav_positions` said nothing
about, so POL-FF-11 cannot protect it and the UAV can fly into a teammate it was never told was there. Giving
up the last cell or two of speed is cheaper than the collision.

**Assumptions:**

- `config.UAV_SPEED` may exceed `config.UAV_OBSERVATION_RADIUS`. If it could not, this rule would never bite
  and could be dropped.

```yaml
id: POL-FF-13
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.within_sight
verified_by: test
status: agreed
```

## POL-FF-14 — The rules are applied in order

> The policy SHALL apply its rules in the order fuel reserve (POL-FF-1), then water (POL-FF-2), then
> threatened out buildings (POL-FF-8), then nearest fire (POL-FF-7), selecting the action of the first rule
> whose condition holds and ignoring the rest.

Each rung is separately reasonable and they conflict constantly: a low UAV carrying water with a building
burning in front of it satisfies three of them at once. The ordering is what decides, it is what a refactor
breaks most quietly, and no test of a single rung in isolation can catch it going wrong.

Verified by observations built to satisfy two rungs at once, checking which one wins. That is the whole
technique: a precedence requirement is only tested by a case where obeying the wrong rule is still a perfectly
defensible action.

```yaml
id: POL-FF-14
satisfied_by:
  - sim/policy/firefighter.py::FirefighterPolicy.action_for
verified_by: test
status: agreed
```
