# `random` — the uninformed baseline

Every UAV picks a movement direction and a speed uniformly at random, ignoring everything it can see.

This policy exists to be beaten. It is the control the other policies are measured against, so what matters
about it is not that it does anything sensible but that it is *uninformed in a specific way*: uniform over the
movement actions, uniform over the speeds, and independent of the observation. A baseline that quietly
favoured one direction, or that reacted to fire at all, would flatter or unfairly penalise everything compared
against it, and nothing in a run's output would show that it had happened.

Inherited obligations: see [`_contract.md`](_contract.md).

## POL-RND-1 — Movement in a uniformly chosen direction

> For each observation, the policy SHALL choose a direction uniformly at random from the movement directions
> 0 to `config.N_ACTIONS` - 1, and SHALL never return `ACTION_STAY` or `ACTION_DUMP_WATER`.

The baseline has to be uniform over the directions to be a fair control. Holding position or dumping water are
informed choices about what to do with a step, so a baseline that made them would no longer be uninformed.

`ACTION_STAY` and `ACTION_DUMP_WATER` sit outside the `0 .. N_ACTIONS - 1` range on purpose, precisely so that
a draw over the movement actions cannot produce them.

```yaml
id: POL-RND-1
satisfied_by:
  - sim/policy/random_policy.py::RandomPolicy.action_for
verified_by: test
status: agreed
```

## POL-RND-2 — Speed in a uniformly chosen amount

> When `config.UAV_SPEED` is at least 1, the policy SHALL choose a speed uniformly at random from the whole
> numbers 1 to `config.UAV_SPEED` inclusive.

Speeds arrived after the baseline did. Drawing them uniformly keeps the baseline as uninformed about how far
to fly as it is about which way, and keeps a run at `UAV_SPEED` of 1 identical to the runs the simulator
produced before speeds existed.

```yaml
id: POL-RND-2
satisfied_by:
  - sim/policy/random_policy.py::RandomPolicy.action_for
verified_by: test
status: agreed
```

## POL-RND-3 — A fleet that cannot fly is still given orders

> When `config.UAV_SPEED` is less than 1, the policy SHALL return a movement direction with a speed of zero
> rather than raising.

A speed of zero is a legitimate configuration, used to hold a fleet still while something else about a run is
measured. Drawing uniformly from an empty range would raise instead.

```yaml
id: POL-RND-3
satisfied_by:
  - sim/policy/random_policy.py::RandomPolicy.action_for
verified_by: test
status: agreed
```

## POL-RND-4 — The observation makes no difference

> Given the same generator state, the policy SHALL return the same actions whatever the observations
> contain.

It is what makes this the control. A baseline that responded to fire, however weakly, would be a policy under
test rather than the thing the policies under test are compared against.

```yaml
id: POL-RND-4
satisfied_by:
  - sim/policy/random_policy.py::RandomPolicy.action_for
verified_by: test
status: agreed
```

## POL-RND-5 — Every draw comes from the run's generator

> The policy SHALL draw both the direction and the speed from `config.SYSTEM_RANDOM`, read at the time the
> policy runs, so that two runs under the same seed produce the same actions.

`config.SYSTEM_RANDOM` is the single source of randomness in the simulator, which is what makes a run
reproducible from its seed. A policy reaching for the module level `random` instead would break that for the
whole simulation, not just for itself.

Reproducibility of the simulation as a whole is checked separately, in `tests/test_reproducibility.py`. What
is required here is narrower: that this policy is one of the things that reproducibility holds for.

**Assumptions:**

- The module is imported as `import config` rather than `from config import SYSTEM_RANDOM`, so that a runner
  replacing the generator reaches this policy. See the note at the top of `sim/policy/random_policy.py`.

```yaml
id: POL-RND-5
satisfied_by:
  - sim/policy/random_policy.py::RandomPolicy.action_for
verified_by: test
status: agreed
```
