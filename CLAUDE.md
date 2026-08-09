# Working in this repository

A wildfire simulator (Mesa 1.x) for evaluating UAV adaptation strategies. `README.md` is the design
document and is worth reading before anything structural.

## Running things

```
python3 -m pip install -r requirements.txt
python3 main.py                  # web interface
python3 headless.py              # batch runs, --policy and --managing among the options
python3 -m pytest                # the suite, from the repository root
python3 tools/trace.py check     # the requirement trace
```

Mesa MUST stay on 1.x. Mesa 2.0 removed `mesa.time` and the tornado-based visualisation the web interface
is built on, so newer versions fail at import.

## Working on a UAV policy

The policies in `sim/policy/` have requirements specifications under `specs/policies/`, and the trace
between requirement, implementation and test is enforced by `tests/test_traceability.py`. So:

1. **Read `specs/policies/<name>.md` before changing the policy.** It is where the behaviour is defined;
   the code is one of the things that has to agree with it.
2. **Changing behaviour means amending or adding a requirement first.** The specification leads the code.
   A change that leaves the specification alone is either a refactor or a bug fix — say which.
3. **A new requirement needs `satisfied_by` and at least one test marked `@pytest.mark.verifies("<id>")`.**
   The suite fails otherwise, which is the point.
4. **Never renumber a requirement id.** Retire it with `status: retired`, which keeps the id out of
   circulation. An id that has meant two different things makes every past review unreadable.
5. **Run `python3 tools/trace.py check` before calling the work done**, and `python3 tools/trace.py report`
   whenever anything about the trace changed — `specs/TRACEABILITY.md` is generated and committed, and a
   test fails when it is stale.

`specs/README.md` is the authoring contract: the field reference, the rules for writing a requirement that
can actually be implemented and tested from, and how the whole thing maps onto an assurance argument. Read
it before writing a requirement rather than copying the shape of an existing one.

Adding a policy is documented in `sim/policy/__init__.py`. Note that a registered policy with no
specification fails `tools/trace.py check`.

## Conventions

These are consistent across the repository and worth matching rather than improving on.

**Settings.** Everything configurable lives in `config.py` at the repository root — deliberately not
inside `sim/`, because it is the file users actually edit. Modules read settings as `config.NAME` at the
point of use, never `from config import NAME`, so that a run overriding one reaches the code. Add a knob
there with the same density of comment as its neighbours, and add it to `config.validate()`.

**Randomness.** `config.SYSTEM_RANDOM` is the only source. Reaching for the module-level `random` breaks
reproducibility for the whole simulation, and `tests/test_reproducibility.py` will catch it.

**Comments.** This codebase explains *why*, at length, in prose above the thing being explained, and the
class docstrings for the policies are close to specifications in their own right. Match that. Imports are
grouped under literal `# python libraries` and `# own python modules` banners, and long files are divided
by `# --- section name ------` rules.

**Tests.** pytest, under `tests/`, mirroring the `sim/` layout. Every test file opens with a module
docstring saying why the tests exist, frequently naming the bug that motivated them. Test names are long
prose sentences. The fixtures in `tests/conftest.py` — `observation`, `snapshot`, `sim_config`,
`make_model`, `uav_speed`, `seed_rng` — are how a test gets a deterministic setup; policy tests build
`Observation` objects directly and never touch the grid or mesa.

**The managing system.** Nothing under `sim/managing/` may import the simulation, the agents, the policies
or mesa. `tests/managing/test_independence.py` enforces it. The two sides meet only in `sim/adapters.py`.
