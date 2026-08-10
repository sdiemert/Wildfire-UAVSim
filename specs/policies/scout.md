# `scout` — searches for fire

Every UAV assigned this policy is on a mission to find fire on the map.

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
