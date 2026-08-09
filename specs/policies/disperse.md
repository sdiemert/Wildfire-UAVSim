# `disperse` — open the gap and nothing else

Two UAVs that end a step on the same cell collide and each rolls for damage; enough of those and the team
flies itself to pieces. Every other policy treats that as a constraint on the way to doing something else,
giving up a cell of speed here and there to stay clear. This one treats it as the whole job.

It is what the managing system allocates to a UAV in trouble — crowded, or down to its last health point, or
both. Giving up on the fire entirely is the point: the UAV is worth more to the run intact and idle than
damaged and busy. The managing system is expected to take it off this policy once the gap has opened, and that
pairing is what makes the arrangement work.

Inherited obligations: see [`_contract.md`](_contract.md).

## POL-DSP-1 — Nobody in view means hold position

> When `observation.uav_positions` is empty, the policy SHALL return `Action.stay()`.

There is nothing to get away from, and this policy has no other reason to move. Flying anyway would burn fuel
and could carry the UAV toward a teammate it cannot see.

```yaml
id: POL-DSP-1
satisfied_by:
  - sim/policy/disperse.py::DispersePolicy.action_for
verified_by: test
status: agreed
```

## POL-DSP-2 — Enough room already means hold position

> When the distance from `observation.pos` to the nearest position in `observation.uav_positions` is at
> least the target separation, the policy SHALL return `Action.stay()`.

The job is done. Continuing to run would push the UAV to the edge of the grid for no gain, and would never
settle, because there is no distance at which "further" stops being available.

```yaml
id: POL-DSP-2
satisfied_by:
  - sim/policy/disperse.py::DispersePolicy.action_for
verified_by: test
status: agreed
```

## POL-DSP-3 — A crowded UAV flies away from the crowd

> When the nearest position in `observation.uav_positions` is closer than the target separation, the policy
> SHALL fly the UAV away from the centre of mass of `observation.uav_positions`, far enough to close the gap
> it is short of and no further.

Away from the centre of mass is the direction that opens the most room against the whole crowd at once, rather
than against whichever teammate happens to be nearest. Stopping at the gap that is missing keeps the UAV from
crossing the grid over a shortfall of one cell.

**Assumptions:**

- UAVs move along one axis per step, so "away from the centre of mass" is the better of the two axes rather
  than a true bearing. The scaling in `escape_target()` is what stops `step_towards()` picking the axis the
  UAV barely needs to move along.

```yaml
id: POL-DSP-3
satisfied_by:
  - sim/policy/disperse.py::DispersePolicy.action_for
  - sim/policy/disperse.py::DispersePolicy.escape_target
verified_by: test
status: agreed
```

## POL-DSP-4 — The escape never ends on a teammate

> The policy SHALL NOT return an action whose flight path contains a position in
> `observation.uav_positions`.

Landing on a teammate is the exact collision this policy exists to avoid. A UAV boxed in on one side can be
sent along a route that passes through one, so the action is trimmed even though `SuperPolicy` will trim it
again against the rest of the fleet: this policy has to be correct when it is flown on its own through
`--policy disperse`.

```yaml
id: POL-DSP-4
satisfied_by:
  - sim/policy/disperse.py::DispersePolicy.action_for
  - sim/policy/base.py::avoid
verified_by: test
status: agreed
```

## POL-DSP-5 — A UAV in the middle of a crowd still picks a way out

> When `observation.pos` is exactly the centre of mass of `observation.uav_positions`, the policy SHALL
> choose a direction at random using `config.SYSTEM_RANDOM` rather than holding position.

There is no "away" to compute, and the UAV is in the worst place on the grid: the middle of the crowd it is
supposed to be escaping. Any direction is better than staying, and drawing from `SYSTEM_RANDOM` keeps the
choice reproducible under a seed.

```yaml
id: POL-DSP-5
satisfied_by:
  - sim/policy/disperse.py::DispersePolicy.escape_target
verified_by: test
status: agreed
```

## POL-DSP-6 — The separation flown to can be allocated per UAV

> The policy SHALL use `config.SECURITY_DISTANCE` as its target separation, unless `configure()` was called
> with a `PolicyParams` carrying a non-zero separation, in which case it SHALL use that value.

It is how the managing system asks a badly boxed in UAV for more room than the rest of the team keeps. Falling
back to `SECURITY_DISTANCE` read at call time, rather than captured when the policy was built, is what lets a
run overriding it reach a policy that was never allocated anything.

This is the only policy that overrides `configure()`. The other four inherit the base implementation and
ignore their parameters, which is correct: the speed cap and the separation that matter to all of them are
enforced by `SuperPolicy` after the policy has chosen. See POL-GEN-8.

```yaml
id: POL-DSP-6
satisfied_by:
  - sim/policy/disperse.py::DispersePolicy.configure
  - sim/policy/disperse.py::DispersePolicy.target_separation
verified_by: test
status: agreed
```
