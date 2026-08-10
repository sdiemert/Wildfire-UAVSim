# `follow-fire` — fly at the nearest visible fire

The simplest thing a UAV can do with what it sees: head for the closest burning cell, and hold position when
there is nothing burning in view.

It is a toy, and knowing why is part of the specification. Targeting the *nearest* burning cell settles a UAV
on the inner edge of a fire and then leaves it sitting in the burnt out core, which on a dense grid scores
worse on MR1 than flying at random. That behaviour is required, not tolerated: this policy is what makes the
point that reacting to what you can see is not the same as reacting usefully, and a version quietly improved
to chase the fire front would stop making it.

Inherited obligations: see [`_contract.md`](_contract.md).

## POL-FOL-1 — Nothing burning in view means hold position

> When `observation.burning_positions()` is empty, the policy SHALL return `Action.stay()` for that UAV.

There is nothing in the observation to fly toward, and this policy does not search. Holding position keeps the
UAV where the fire is most likely to reach it next, and keeps the baseline comparison honest by not adding an
exploration behaviour that was never specified.

A UAV over bare ground sees no cells at all, and a UAV over unburnt vegetation sees cells but none of them
burning. Both are this case, and so is a third: a UAV inside a smoke plume, whose window has been emptied by
the occlusion rather than by there being nothing in it. The policy cannot tell the three apart and is not
meant to — `observation.burning_positions()` is what it decides from, and a fire it cannot see is a fire it
cannot follow.

```yaml
id: POL-FOL-1
satisfied_by:
  - sim/policy/follow_fire.py::FollowFirePolicy.action_for
verified_by: test
status: agreed
```

## POL-FOL-2 — The nearest burning cell is the target

> When `observation.burning_positions()` is not empty, the policy SHALL select as its target the burning
> position closest to `observation.pos` by Euclidean distance.

Nearest is the only ordering available to a UAV that knows nothing about the fire beyond its own window. It is
also what makes this policy behave badly in a way worth demonstrating.

```yaml
id: POL-FOL-2
satisfied_by:
  - sim/policy/follow_fire.py::FollowFirePolicy.action_for
  - sim/policy/base.py::nearest
verified_by: test
status: agreed
```

## POL-FOL-3 — Only burning cells are targets

> The policy SHALL NOT select a cell reported in `observation.cells` as not burning, even when it is closer
> to the UAV than every burning cell.

Unburnt vegetation is what the UAVs are there to protect, not to fly at. Consulting `burning_positions()`
rather than cells is what keeps the two apart.

```yaml
id: POL-FOL-3
satisfied_by:
  - sim/policy/follow_fire.py::FollowFirePolicy.action_for
  - sim/policy/observation.py::Observation.burning_positions
verified_by: test
status: agreed
```

## POL-FOL-4 — Already over the target means hold position

> When the selected target is `observation.pos` itself, the policy SHALL return `Action.stay()`.

A UAV standing on a burning cell has arrived. Without this it would be asked to fly a distance of zero, which
is a movement action carrying no movement and would be reported as flight in the logs.

This is where the policy leaves a UAV parked in a burnt out core: the cell under it keeps being the nearest
burning one until it stops burning, by which time the fire front has moved on.

```yaml
id: POL-FOL-4
satisfied_by:
  - sim/policy/base.py::step_towards
verified_by: test
status: agreed
```

## POL-FOL-5 — One axis per step, the larger gap first

> When flying to a target, the policy SHALL move along one axis only, choosing the axis with the larger
> remaining gap, at a speed of the smaller of that gap and `config.UAV_SPEED`.

UAVs move along one axis at a time, so a diagonal approach has to be a staircase. Closing the larger gap first
keeps the staircase to as few turns as possible, and capping at the remaining gap stops the UAV overshooting a
target it could reach this step.

```yaml
id: POL-FOL-5
satisfied_by:
  - sim/policy/base.py::step_towards
verified_by: test
status: agreed
```

## POL-FOL-6 — A diagonal target is approached along a randomly chosen axis

> When the remaining gaps on both axes are equal, the policy SHALL choose between the two axes at random
> using `config.SYSTEM_RANDOM`, rather than always preferring the same one.

A fixed tie break would send every UAV facing a diagonal target along the same axis, so a team approaching one
fire would drift into a single line and collide. Drawing from `SYSTEM_RANDOM` keeps the choice reproducible
under a seed while still spreading the team.

```yaml
id: POL-FOL-6
satisfied_by:
  - sim/policy/base.py::step_towards
verified_by: test
status: agreed
```
