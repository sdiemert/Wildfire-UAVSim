# The policy contract

Obligations that bind **every** policy in `sim/policy/`, whatever it is trying to achieve. A policy that
breaks one of these does not misbehave, it breaks the simulator: `WildFireModel.set_drone_dirs()` matches the
returned actions to UAVs by position in the list, and `UAV.move()` trusts the direction it is given.

These requirements are not restated in the individual policy specifications. Each of those covers only what
makes that policy different.

The implementation trace for the requirements here points at `sim/policy/base.py`, where the obligation is
stated, and at `sim/policy/action.py`, where the type that carries it is defined — not at the five policies
that honour it. The evidence works the same way: the contract suite in `tests/policy/test_policy_interface.py`
is parametrised over `sim.policy.REGISTERED`, so one tagged test is evidence for every registered policy at
once, and a policy added tomorrow is held to these requirements from the moment it is registered.

## POL-GEN-1 — One action per UAV, in the order the observations arrived

> A policy SHALL return a list of exactly as many actions as it was given observations, with the action at
> each position being the action for the UAV whose observation was at that position.

`WildFireModel.set_drone_dirs()` pairs actions with UAVs by position alone. A list of the wrong length raises
or silently drops a UAV's orders, and a list in the wrong order flies every UAV somewhere it was never sent.

Length and order are one requirement rather than two because they are one property: the positional
correspondence between the two lists. They take two tests to demonstrate, which is fine — evidence is
allowed to be plural, and both are tagged.

```yaml
id: POL-GEN-1
satisfied_by:
  - sim/policy/base.py::Policy.select_actions
verified_by: test
status: agreed
```

## POL-GEN-2 — Only actions the simulator can carry out

> Every element a policy returns SHALL be an `Action`, or a value `Action.coerce()` accepts, whose direction
> is one of `ACTION_RIGHT`, `ACTION_DOWN`, `ACTION_LEFT`, `ACTION_UP`, `ACTION_STAY` or `ACTION_DUMP_WATER`.

`UAV.advance()` dispatches on the direction and has no branch for anything else, so a direction outside this
set is a crash or, worse, an index into `MOVEMENT_VECTORS` that happens to be in range.

`Action.coerce()` is what makes the "or a value it accepts" half true: a bare direction index means one cell,
which is how policies written before speeds existed keep working unchanged.

```yaml
id: POL-GEN-2
satisfied_by:
  - sim/policy/action.py::Action
  - sim/policy/action.py::Action.coerce
verified_by: test
status: agreed
```

## POL-GEN-3 — No policy asks for more speed than a UAV has

> The speed of every action a policy returns SHALL be at least zero and at most `config.UAV_SPEED`, read at
> the time the policy runs.

A UAV never covers more than `UAV_SPEED` cells whatever it is asked for, so an over-large speed is not
dangerous, it is dishonest: the logs and the managing system both read the requested speed, and a policy that
habitually asks for more than it can have makes them describe a run that did not happen.

`step_towards()` is where the cap is actually applied for the policies that home in on something, which is why
it carries the trace alongside the type.

**Assumptions:**

- `config.UAV_SPEED` is read at call time rather than captured at import, which is why a run that overrides it
  reaches the policies. Every policy here imports config as a module for that reason.

```yaml
id: POL-GEN-3
satisfied_by:
  - sim/policy/base.py::step_towards
  - sim/policy/action.py::Action
verified_by: test
status: agreed
```

## POL-GEN-4 — Actions that do not move a UAV carry no speed

> When the direction of a returned action is `ACTION_STAY` or `ACTION_DUMP_WATER`, its speed SHALL be zero.

Speed is meaningless for both of them, and a non-zero one would be read as a distance by anything summing the
movement a run produced. Pinning it at zero keeps two actions that mean the same thing from comparing unequal.

```yaml
id: POL-GEN-4
satisfied_by:
  - sim/policy/action.py::Action.stay
  - sim/policy/action.py::Action.dump
  - sim/policy/action.py::Action.coerce
verified_by: test
status: agreed
```

## POL-GEN-5 — An empty team is not an error

> When a policy is given an empty list of observations, it SHALL return an empty list of actions.

A run can lose its last UAV to collisions or an empty tank, and the model keeps stepping afterwards. The
policy is still called, and has to survive it.

```yaml
id: POL-GEN-5
satisfied_by:
  - sim/policy/base.py::Policy.select_actions
verified_by: test
status: agreed
```

## POL-GEN-6 — Every policy is identifiable by name

> Every policy SHALL carry a non-empty string 'name' that no other registered policy uses, and str() of the
> policy SHALL return that name.

The name is the identifier the `--policy` option, the web interface dropdown, the `UavDirective` the managing
system sends, and `POLICY_COLORS` on the display all key on. Two policies sharing one makes the registry
silently lose whichever was registered first.

```yaml
id: POL-GEN-6
satisfied_by:
  - sim/policy/base.py::Policy.name
  - sim/policy/base.py::Policy.__str__
verified_by: test
status: agreed
```

## POL-GEN-7 — A policy decides from the observations and nothing else

> `Policy.select_actions` SHALL take the list of observations as its only parameter, so that a policy has no
> access to grid state beyond what each UAV can see.

Partial observability is the property that makes a run mean anything: a policy handed the whole grid would be
solving a different problem from the one the UAVs face. Enforcing it at the signature is what makes it
structural rather than a convention a policy could quietly break.

The signature is the whole of the guarantee. A policy can still reach for `config`, and does — that is how
`UAV_SPEED` and `WATER_DROP_RADIUS` get read — but `config` holds the settings of the run, not the state of
the grid, so nothing there tells a UAV about a cell it cannot see.

```yaml
id: POL-GEN-7
satisfied_by:
  - sim/policy/base.py::Policy.select_actions
  - sim/policy/observation.py::Observation
verified_by: test
status: agreed
```

## POL-GEN-8 — Configuration is optional and never required

> A policy SHALL accept a call to `configure()` with a `PolicyParams` or with `None` before
> `select_actions()`, and SHALL remain able to select actions afterwards whether or not it was ever
> configured.

`SuperPolicy` calls `configure()` on every policy it holds, including the four that have no setting of their
own and inherit the base implementation that ignores it. A policy that needed configuring before it could run
would break every path that builds one directly, which is what `--policy` and the tests do.

The speed cap and the separation in `PolicyParams` are deliberately *not* obeyed here: `SuperPolicy` enforces
both after the policy has chosen. That is what lets every policy written before the managing system existed
keep working untouched, and it is why the base `configure()` ignoring its argument is correct rather than
lazy.

```yaml
id: POL-GEN-8
satisfied_by:
  - sim/policy/base.py::Policy.configure
  - sim/policy/params.py::PolicyParams
verified_by: test
status: agreed
```

## POL-GEN-9 — Every registered policy is reachable by name

> `build_policy()` SHALL return an instance of the registered class for every name in `POLICIES`, and SHALL
> raise KeyError naming the available policies for any other string.

It is the single door into the policy layer, used by the `--policy` option, the web interface dropdown and the
managing system's effector. A silent miss would start a run under a policy nobody asked for.

```yaml
id: POL-GEN-9
satisfied_by:
  - sim/policy/__init__.py::build_policy
  - sim/policy/__init__.py::POLICIES
verified_by: test
status: agreed
```
