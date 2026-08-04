# Project overview

## Project description

Wildfire-UAVSim is a customizable wildfire tracking simulator that enables
the evaluation of diverse adaptation strategies. Among its many configuration parameters, the forest area is customizable with different densities of vegetation, as well as fire and smoke dispersion patterns that are affected by factors such as wind, conforming different observability conditions. The configuration options of our simulator also allow to place a team of UAVs in charge of tracking the fire over the forest area. Wildfire-UAVSim provides a graphical web interface native from Mesa framework, executed by the simulator, in order to keep track of how the simulation evolves in time.

## Files structure

Three things sit at the root, and everything else is inside the `sim` package:

```
config.py     every simulation setting; this is the file you edit
main.py       launches the web interface
headless.py   runs simulations without it

sim/
  formulas.py       shared maths: distances, fuel costs, extinguishing odds
  model.py          WildFireModel, the main loop and the state of a run
  fire_spread.py    how likely every cell is to catch fire, for the whole grid at once
  environment.py    Wind and Smoke
  agents/           what stands on the grid: Fire, UAV, Base, BaseTile, OutBuilding
  policy/           the policies that decide where each UAV flies
  managing/         the MAPE-K managing system that decides which policy each UAV flies
  adapters.py       the sensors and effectors joining the two; the only module importing both
  adaptive.py       AdaptiveWildFireModel, the model with a managing system over it
  gui/              the Mesa web interface
  cli/              the headless runner behind headless.py

tests/          the unit tests, mirroring the package
```

The simulator can be run as a plain **managed system**, which is what it has always been, or as a
**self-adaptive system**: the same simulation with a managing system over it that reallocates policies to
UAVs while the run is going. `MANAGING_SYSTEM` in `config.py` is the switch. See
[The managing system](#the-managing-system).

### `config.py`

This python file holds the variables used to set the simulation execution configurations. It stays at the root of the project, rather than inside `sim`, because it is the one file most users need to open. It is organised into sections in the order a run is built up — the environment, the forest, the ignition, the wind, the smoke, the UAVs, the firefighting extension and the drawing colours — and each variable carries a one line description and its bounds next to its value. [Common variables configuration](#common-variables-configuration) below is the longer form of the same material.

Every module reads its settings as `config.NAME` at the point of use rather than copying the values in, which is what lets `headless.py --set` override any of them for a single run.

### `sim/agents/`

This python package holds the agents that stand on the grid, one module per kind: `fire.py` (a cell of vegetation, which holds the fuel and does the burning), `uav.py` (a drone, which observes, flies and dumps water), `base.py` (the home base UAVs refill at, and the tiles of its footprint) and `out_building.py` (a building worth defending). All of them are re-exported, so `from sim import agents` then `agents.UAV` reaches any of them.

The wind and the smoke are in `sim/environment.py` instead: neither holds a cell on the grid, and neither is stepped by the scheduler.

### `sim/model.py`

This python file holds the logic for managing the wildfire simulation, by utilizing the agents above. It owns the grid, the schedule, the ignition, the collision and fuel resolution, and the MR1/MR2 monitoring metrics.

### `sim/fire_spread.py`

This python file works out how likely every cell of the grid is to catch fire, for the whole grid at
once, and is by far the largest influence on how fast a simulation runs.

The rule itself is unchanged, and is still written out cell by cell in `Fire.probability_of_fire()`
in `sim/agents/fire.py`. That version asks each cell to walk its neighbourhood, which repeats the same
distance calculation millions of times per run and used to account for over 99% of the run time.
Because a cell's influence on its neighbour depends only on the offset between them, the same
quantity can be obtained for every cell in a single pass over the grid, which is what this file does.
A full 90 step run of the default configuration went from about 16 seconds to about 0.8 seconds.

Both versions are kept, and `tests/test_fire_spread.py` checks them against each other cell by cell,
under each wind setting, at the edges of the grid and with sparse vegetation. **If you change how the
fire spreads, change it in both places**, or that test will fail.

One caveat on reproducibility. With the wind switched off or with `FIXED_WIND = True`, seeded runs
give exactly the results they gave before this file existed. With composed wind (`FIXED_WIND =
False`) the wind direction is drawn per cell in one go rather than one cell at a time, so runs are
statistically the same but a given seed no longer reproduces older results.

### `sim/formulas.py`

This python file holds the maths shared between the model, the agents, the policies and the interface: Euclidean distance, the fuel a step of flight costs, the odds of a water drop extinguishing a cell. It is kept in one place so that a policy estimating how far its remaining fuel will take it works it out exactly the way the model charges for it.

### `sim/gui/`

This python package holds the Mesa web interface that `main.py` launches: `app.py` wires it together, `portrayal.py` says how each agent is drawn, and `canvas_grid.py`, `status_sidebar.py`, `top_bar.py` and `policy_selector.py` are the elements on the page — the last of these holds both `PolicySelector`, which moves a control into the strip above the grid, and `ControlGate`, which greys one control out while another makes it meaningless. `canvas_grid.py` is a Mesa class modified to make UAV observation areas visible; it is not really necessary to change these files.

### `sim/cli/`

This python package runs simulations without the graphical interface, with logging and optional parallel execution — `main.py` parses the arguments, `runner.py` executes one run, `batch.py` runs several in parallel, `overrides.py` implements `--set` and `--seed`, and `reporting.py` handles the logging and the summary. Run `python3 headless.py --help` for the available options.

### `sim/policy/`

This python package holds the policies that decide where each UAV flies. `base.py` defines the abstract `Policy` interface, `observation.py` defines the `Observation` a UAV receives, `action.py` defines the `Action` it returns, and every concrete policy lives in its own file (`random_policy.py`, `follow_fire.py`, `firefighter.py`). The policy in use can be picked from the dropdown on the web interface, or with the `--policy` option of `headless.py`.

A policy receives one `Observation` per UAV and returns one `Action` per UAV: a direction and a speed.

```python
from sim.policy import Action, Policy
from config import ACTION_UP

class MyPolicy(Policy):
    name = "my-policy"

    def select_actions(self, observations):
        # every UAV flies three cells north, whatever it sees
        return [Action(ACTION_UP, 3) for _ in observations]
```

`Action.stay()` holds position and `Action.dump()` drops water; both carry a speed of zero. A UAV never covers more than `UAV_SPEED` cells in a step, whatever speed is asked for, and stops early at the edge of the grid. A policy may also return a bare direction index, or a `(direction, speed)` pair, which are coerced into an `Action` — a bare direction means one cell per step, as it did before speeds existed.

An `Observation` reports what one UAV can see: `pos`, the `cells` in view with their burning state, and `uav_positions`, the cells the **other UAVs in view** are standing on. Flying onto one of those is a collision and costs both UAVs health points, so a policy that moves its team about has to keep it apart. Three helpers in `sim/policy/base.py` are there for that:

```python
from sim.policy import avoid, flight_path, by_distance

flight_path(pos, action)          # the cells the action would take the UAV through, in order
avoid(pos, action, blocked)       # the same action, trimmed to stop short of any 'blocked' cell
by_distance(pos, positions)       # positions ordered nearest first, for picking an unclaimed target
```

`FirefighterPolicy` shows the pattern: it claims a fire per UAV so that no two are sent to the same cell, then trims each action with `avoid()` so that no UAV flies into one it can see or lands where a teammate has already been sent. The cells of the home base are deliberately left out of `blocked` — `observation.base_footprint()` reports them — because UAVs do not collide there and must be able to land to refill.

It also never asks a UAV to fly further than `UAV_OBSERVATION_RADIUS`. This matters whenever `UAV_SPEED` is the larger of the two, as it is by default (`5` against `4`): a flight that ends outside the observation window lands on a cell `uav_positions` said nothing about, so the UAV can fly into a teammate it was never told was there. Giving up the last cell of speed is cheaper than the collision.

With the firefighting extension on, an `Observation` also carries `has_water`, `base_pos`, `base_cells` and `building_positions`; `at_base()` is true anywhere on the base footprint. With the fuel extension on it carries `fuel` and `fuel_capacity`, read through `fuel_fraction()` and `low_fuel()`; both are `None` when fuel is not being tracked, and `low_fuel()` is then always `False`, so a policy that ignores fuel flies exactly as it did before.

### `sim/managing/`

This python package holds the managing system: a MAPE-K loop that watches how a run is going and decides which policy each UAV should be flying. It is described in full under [The managing system](#the-managing-system).

`contract.py` holds the frozen messages that cross the boundary and `ports.py` the `Sensor` and `Effector` interfaces. The five MAPE-K parts have a sub-package each — `monitor/`, `analyze/`, `plan/`, `execute/` and `knowledge/` — and every one of them has the same shape: `base.py` defines the role, any siblings are alternative implementations of it, and `__init__.py` registers them all and says how to add another. `registry.py` is the name-to-class lookup they share, and `systems.py` is the catalogue of named managing systems built out of them — adding one is an entry in a tuple there. `loop.py` assembles the components of a managing system that runs here; `remote.py` is the whole loop living on a server.

Nothing in this package imports the simulation — not the model, not the agents, not the policies, not mesa — and `tests/managing/test_independence.py` fails if that ever changes.

### `tests/`

This directory holds the unit tests, grouped to mirror the package: `tests/agents/`, `tests/policy/`, `tests/managing/`, `tests/cli/` and `tests/gui/`, with the tests that cover a single module at the root of `sim` — or cut across everything — at the top. See [Running the tests](#running-the-tests).

# Installation setup

In the following subsections, the installation process for executing the project will be explained.

## Installing Pycharm Community Edition IDE

The first step is to download and install Pycharm Community Edition IDE to easily run and set up the project and its dependencies. For Linux users (this project was initially tested on Ubuntu 22.04.2 LTS), they can use the `snap` command in cmd (pre-installed from Ubuntu 16.04 LTS and later) as a fast installation option. Users must execute the command `sudo snap install pycharm-community --classic` in cmd for installing Pycharm Community Edition.

Despite this project was initially tested on Ubuntu 22.04.2 LTS, it has been later tested on Windows and Mac too. For checking system requirements, and information about the installation process, please visit https://www.jetbrains.com/help/pycharm/installation-guide.html.

## Opening the project

First, extract the Wildfire-UAVSim downloaded package in any folder. Second, open Pycharm by executing the command `pycharm-community` in cmd, or searching for the executable in the computer.
Then, the projects window should be opened. Next, the user has to click on `Open`, select the extracted project folder, and click `OK`. A window should appear to select between light editor, and project editor.
Select project editor. For openning the project more times, repeat same process.

## Installing dependencies

Once the project is opened, some dependencies are necessary. To install them, first go to `Settings > Project > Python Interpreter`, then select the desired Python interpreter
for executing the project. As default `/usr/bin/python3.10` should appear in the `Python Interpreter:` tab, which already contain some default dependencies if Ubuntu 22.04.2 LTS is installed. For other Python interpreters,
other dependencies may be needed to be installed. On the same Pycharm configuration window, click on `+` icon, and search for the following dependencies (the user should specify the same version as the one used when developing the project. Version can be specified by clicking on the "Specify version" checkbox):

<ul>
  <li>Mesa (v.1.2.1)</li>
  <li>numpy (v1.24.2)</li>
  <li>matplotlib (v3.7.1)</li>
  <li>pytest (only needed to run the unit tests)</li>
</ul>

Alternatively, all of them can be installed from the command line with:

```bash
python3 -m pip install -r requirements.txt
```

## Execution of the project

Once project is opened, and dependencies were installed, `main.py` can be executed by selecting the file, right mouse click, and clicking on `Run 'main'` (shortcut should be `Ctrl+Mayus+F10`).
A web page interface should appear, with the wildfire grid, and buttons for configuring the simulation.

From the command line, run either entry point from the root of the project:

```bash
python3 main.py            # the web interface
python3 headless.py        # a simulation without it, see --help
```

Both have to be run from the project root, because that is where `config.py` and the `sim` package are found. There is no need to install the project; if you would rather have `wildfire-gui` and `wildfire-headless` on your path, `python3 -m pip install -e .` provides them.

# Running the tests

The unit tests live in the `tests/` directory and are run with [pytest](https://docs.pytest.org/). They are grouped to mirror the package — `tests/policy/` for the UAV policies, which need neither a grid nor the Mesa framework, `tests/agents/` for the agents on the grid, and the tests covering the fire spread, the run lifecycle, the configuration and reproducibility at the top. The whole suite finishes in well under two seconds.

## From the command line

From the root of the project:

```bash
python3 -m pytest
```

Useful variations:

```bash
python3 -m pytest tests/policy                          # every policy test
python3 -m pytest tests/policy/test_follow_fire_policy.py   # a single file
python3 -m pytest -k "holds_position"                   # tests whose name matches a pattern
python3 -m pytest -q                                    # quiet, one line per file
python3 -m pytest -x                                    # stop at the first failure
```

Test discovery is configured in `pyproject.toml`, which also puts the project root on the import path so that `import config` and `from sim.policy import ...` work from inside `tests/`.

## From Pycharm

Right mouse click on the `tests` directory and select `Run 'pytest in tests'`. Individual tests can also be run with the green arrow shown next to each test function.

## Writing tests for a new policy

Policies only ever receive `Observation` objects, so a test can describe exactly what a UAV sees without building a grid. The `observation` fixture in `tests/conftest.py` creates them:

```python
def test_moves_toward_a_fire_on_its_right(observation, uav_speed):
    uav_speed(5)
    policy = MyPolicy()
    obs = observation(pos=(5, 5), burning=[(8, 5)], unburnt=[(4, 5)])
    assert policy.select_actions([obs]) == [Action(ACTION_RIGHT, 3)]
```

`pos` is where the UAV is, `burning` and `unburnt` are the cells it can see; cells outside its observation radius are simply left out. `uavs=[(5, 7)]` puts other UAVs in view, for testing that a policy keeps its team apart, and `fuel=10` gives the UAV a part empty tank, defaulting the capacity to `UAV_FUEL`. The `uav_speed` fixture pins `UAV_SPEED` for the test, so an expected speed does not depend on what `config.py` is set to. For a policy that makes random choices, the `seed_rng` fixture replaces `config.SYSTEM_RANDOM` with a seeded generator so the result is reproducible:

```python
def test_is_reproducible(observation, seed_rng):
    policy = MyPolicy()
    seed_rng(42)
    first = policy.select_actions([observation(pos=(5, 5))])
    seed_rng(42)
    assert policy.select_actions([observation(pos=(5, 5))]) == first
```

The contract tests in `tests/policy/test_policy_interface.py` are parametrised over every policy in the registry, so a newly registered policy is automatically checked for returning one valid `Action` per UAV, keeping its speeds within `UAV_SPEED`, handling an empty view, and having a usable name.

Tests about the movement itself — how far a UAV actually gets — need a grid, and live in `tests/agents/test_uav_speed.py`.

# Graphical interface functionalities

When executing the project as explained above, a web page hosted in http://127.0.0.1:8521/ should appear in user's default browser. Port can be modified in `sim/gui/app.py` if user has the default one already busy.

Everything used to drive a run sits in the bar along the top of the page: the speed slider, the step the run has reached, and the buttons. The status panel is down the left hand side, and the policy in use is picked above the grid on the right. The relevant graphical interface elements are:

### `Grid`

The grid with generated cells, with vegetation, fire, smoke, and UAVs, can be seen in the center of the screen.

### `Start button`

The start button allows to run the simulation without stopping. It becomes `Stop` while the simulation is running, and `Done` once the run has reached `BATCH_SIZE` steps.

### `Step button`

The step button allows to execute one time step at a time.

### `Reset button`

The reset button allows to execute the `reset()` method, inherited and overwritten from Mesa framework class `mesa.Model`, into WildFireModel class, inside `sim/model.py`.

### `FPS`

It is a slider that allows to set the frames per second (FPS) velocity for the graphical visualization of the simulation execution. Each frame corresponds to one time step. Its range goes from 1 to 20 FPS, taking into account that, counterintuitively, 0 FPS set the fastest FPS velocity. One reason why the simulation might seem not be playing fluently could be the setting of the `FIRE_SPREAD_SPEED` variable referenced below.

### `Step counter`

Indicates the current time step of the simulation, beside the buttons that advance it.

### `Status panel`

The panel down the left hand side reports the monitoring metrics, the state of the home base and the out buildings, and a line per UAV with its position, its health and the water it is carrying. Figures turn amber and then red as whatever they measure is used up.

With `MANAGING_SYSTEM` set to anything but `none` it also gains a **Managing system** section, kept to a few lines because vertical space beside the map is the scarce thing:

* **which managing system is running**, and where it lives, on a line of its own — `defensive · local`.
* **what it is made of**, but only the components that are *not* the default for their role: `cautious · defensive`. A system built entirely from the defaults says nothing here, because its name has already said it. This is also what shows a combination `--mape` produced that no registered name describes.
* **what the team is flying right now**, as one proportional bar of the whole team in the same colours the UAVs are drawn in on the map, so the panel doubles as the map's key. One line however many policies are in play.
* **why**, in the planner's own words, held to two lines with the whole of it on hover.

Anything that means the run is being managed less than it was asked to be — a remote system that fell back, directives the effector refused — appears in red only when it happens. Each UAV's line then shows the policy it has been allocated, in that policy's colour, next to its position. See [The managing system](#the-managing-system).

### `Managing system` and `UAV policy`

Two dropdowns are stacked at the right hand end of the strip above the grid. Each overrides the matching
setting in `config.py` **for that run only** — nothing is written back, so pressing `Reset` with different
settings builds a different model rather than changing the configuration for everything built afterwards.
Press `Reset` after changing either of them.

| Control | Overrides | Values |
|---|---|---|
| `Managing system` | `MANAGING_SYSTEM` | every managing system registered in `sim/managing/systems.py`: `none` — the unmanaged baseline; `static` — the loop without adaptation, the control arm; `heuristic` — the default; `defensive`; `reactive`; `remote` — the whole loop on the server at `MANAGING_SYSTEM_URL`. One added there appears here without any further change |
| `UAV policy` | — | the rule each UAV flies |

Being able to switch between the three from the page is what makes the comparison a matter of two clicks
rather than an edit and a server restart.

**How they interact.** `UAV policy` is only live while `Managing system` is `none`; otherwise it is greyed
out. That is not a cosmetic choice — a managing system allocates a policy to each UAV itself and overwrites
whatever the run started under within a few steps, so leaving the control enabled would be a promise the
page cannot keep. While it is greyed out it is held at `DEFAULT_UAV_POLICY`, which is the policy the team
actually starts under and the one a UAV with nothing wrong with it is put back on, so what is shown is what
is used.

If you want an unmanaged `random` baseline, set `Managing system` to `none` and pick `random`.

### `Colours`

The map is deliberately kept light. Vegetation runs from near white to a mid green, and the fire from pale yellow to a bright red orange, so that the things worth finding at a glance stay the darkest marks on it: the UAVs are dark, the home base is a deep blue block, and the out buildings are brown. A UAV is outlined in white, which is what keeps it visible on the two backgrounds as dark as it is — the base and burnt ground — and the square marking what it can see is drawn in a lighter slate, so that a team of any size does not bury the map under its own observation windows. All of it is in the `Colours` section of `config.py`.

With `COLOUR_UAVS_BY_POLICY` on, which is the default, a UAV is drawn in the colour of the policy it is flying rather than all of them in the same near black. Which policy each UAV is on *is* the whole of what the managing system decided, and reading it off the panel means looking away from the map to find out what the map is showing; in `POLICY_COLORS` the allocation becomes a shape — a team turning crimson as fire closes on the base is the managing system working, seen at a glance. Every colour in that ramp is dark for the reason the near black was: a lighter one disappears into the vegetation. `firefighter` keeps the old near black, so an unmanaged run looks exactly as it always did, and a policy with no colour of its own is drawn as an ordinary UAV. Set `COLOUR_UAVS_BY_POLICY = False` for the plainer map, where a UAV is a UAV and nothing else.

# The managing system

Setting `MANAGING_SYSTEM` in `config.py` to anything but `none` turns the simulator from a **managed
system** into a **self-adaptive system**.

With it at `none`, every UAV flies one policy, chosen before the run starts and never reconsidered however
the run goes. Otherwise a *managing system* watches the run and reallocates a policy — and a set of
parameters — to each UAV as things change, with two goals: keep the home base from burning down, and keep
the team from flying into itself.

There is more than one managing system. Each is a named combination of the five MAPE-K components, listed
in [The managing systems there are](#the-managing-systems-there-are), and comparing them over the same
seeds is what the whole arrangement is for.

## Managed and managing

```
a local managing system                       a remote one

┌───── MANAGING SYSTEM (sim/managing/) ─────┐  ┌──── server ─────────────────────┐
│  Analyse ──▶ Plan          Knowledge      │  │  Analyse ─▶ Plan   Knowledge    │
│     ▲          │                          │  └────▲──────────┼─────────────────┘
│  Monitor    Execute                       │       │ snapshot │ allocation (JSON)
└─────┼──────────┼──────────────────────────┘  ┌────┼──────────┼─────────────────┐
      │          │                             │ Monitor    Execute   remote.py  │
      │          │                             └────┼──────────┼─────────────────┘
  Sensor.read()  Effector.apply()      ports: sim/managing/ports.py
   ─▶ FleetSnapshot ◀─ Allocation      messages: sim/managing/contract.py
┌─────┼──────────┼──────────────────────────────────┼──────────┼─────────────────┐
│  ModelSensor   AllocationEffector                                sim/adapters.py│
└─────┼──────────┼──────────────────────────────────────────────────────────────-┘
┌─────┴──────────┴───────────────────────────────────────────────────────────────┐
│  WildFireModel ── SuperPolicy ── { firefighter, defend-base, disperse, ... }    │
│                   per UAV dispatch + fleet wide traffic pass   MANAGED SYSTEM   │
└────────────────────────────────────────────────────────────────────────────────┘
```

The sensor and the effector stay on this side either way, because they *are* the simulation's own
interface — a sensor reads a model object and an effector writes to one, and neither can be anywhere else.
In a real deployment they would be the radio link to the fleet. Everything that could be called deciding
is on whichever side the selected managing system lives.

The managing system reaches the simulation through exactly two things: a **sensor** that reads and an
**effector** that writes. It has no other access, and this is enforced rather than merely intended —
nothing in `sim/managing/` imports `sim.model`, `sim.agents`, `sim.policy` or `mesa`, and
`tests/managing/test_independence.py` walks every module in the package and fails if that ever stops being
true. The adapters that satisfy the two interfaces live in `sim/adapters.py`, which is the one module in
the project that imports both halves.

That independence is what makes `remote` possible without redesigning anything: code that was never able
to reach the simulation loses nothing by being moved to another machine.

## The loop, and the five parts it is made of

`ManagingSystem.tick(step)` runs one turn, and `AdaptiveWildFireModel.step()` calls it once before each
simulation step — so the loop always reads a settled world, and an allocation takes effect on the step
after the reading that prompted it.

| Step | What it does | Where the implementations live |
|---|---|---|
| **Monitor** | `sensor.read()` builds a `FleetSnapshot` and files it in the Knowledge base | `monitor/` |
| **Analyse** | judges the snapshot into `Symptoms`: base threat 0–3, which UAVs are crowded, which are at risk. If nothing is wrong the turn ends here, before Plan | `analyze/` |
| **Plan** | turns snapshot and symptoms into an `Allocation`: one directive per UAV, each a policy name and its parameters | `plan/` |
| **Execute** | `effector.apply()` validates every directive and writes the ones that survive | `execute/` |
| **Knowledge** | bounded history of snapshots, the allocation in force, and the hysteresis streaks | `knowledge/` |

Each of the five is a **role**, and every role has a registry of implementations to choose from. A managing
system is one named combination of them, so which analyser and which planner are running is a property of
the run rather than of the code — that is what makes comparing two ways of managing the same fleet a matter
of `--managing <name>` rather than of editing a file.

### What the managing system is allowed to see

`FleetSnapshot` is the whole of it, and it comes from two sources:

* **the UAVs.** Each is asked what it can see through the same `UAV.observe()` the policies get, so the
  managing system is exactly as partially sighted as the team it manages. It learns nothing about a part of
  the map nobody is looking at, and a team that loses UAVs goes blind where they were. Each UAV also
  reports its own state **and the policy it is currently flying**, which is what closes the loop: the
  managing system sees the effect of its own last decision, not just the state of the world.
* **the home base**, which is modelled as having a fire sensor of its own covering `BASE_SENSOR_RADIUS`
  cells beyond its footprint, reported whether or not any UAV is nearby. Without it the managing system
  could be blind to fire reaching the very asset it exists to protect, simply because it had sent the team
  elsewhere.

### What it is allowed to change

One `UavDirective` per UAV: a policy name, plus `PolicyParams` — `speed_cap`, `separation`, `fuel_reserve`
and a free `extra` dictionary. It cannot fly a UAV, only decide what rule the UAV flies itself by.

`AllocationEffector` is a **trust boundary**, not just a channel. Every directive is checked against the
simulation that has to carry it out — the UAV exists, it is still flying, the policy is registered, the
parameters are in bounds — and one that fails is dropped and logged rather than raised. A managing system
that has gone wrong should cost a run its adaptation quality, not its completion.

## The policies it allocates

| Policy | What a UAV under it does |
|---|---|
| `firefighter` | attack the nearest fire, refill at the base. The default working policy |
| `defend-base` | attack the fire nearest **the base**, not the nearest fire; hold station over the base when nothing threatens it |
| `disperse` | give up on the mission and open the gap to nearby team mates until there is room |
| `follow-fire`, `random` | the pre-existing baselines |

`defend-base` and `disperse` are new, and are the levers for the two goals. All five are ordinary policies:
they appear in the `--policy` option and the web interface dropdown, and are covered by the same
parametrised contract tests as the others.

### `SuperPolicy`

The team flies a `SuperPolicy`, which implements the ordinary `Policy` interface — so `WildFireModel` is
untouched and unaware, still holding one policy and calling `select_actions()` once a step. It does two
things:

1. **dispatch.** UAVs are grouped by the policy and parameters they were allocated, and each group is
   handed to its policy in **one call**. Grouping rather than asking per UAV is what preserves the team
   level reasoning the basic policies already do — `FirefighterPolicy` can only avoid sending two UAVs to
   one fire if it is shown both in the same call. A uniform allocation therefore behaves identically to
   running that policy on its own.
2. **a fleet wide traffic pass.** Every action is then trimmed against every other: speed capped to what
   the UAV was allocated, and flight trimmed so no UAV ends its step on a cell another holds or has been
   sent to. This is new capability, not just relocated code — `FirefighterPolicy` deconflicts its own team
   but has no way of knowing about a UAV flying `defend-base` on the next cell, because that UAV was never
   in its call. Without a fleet wide pass, a mixed allocation would collide *more* than either policy does
   alone.

## The managing systems there are

Each of the five MAPE-K steps is a **role** with a registry of implementations, and a **managing system** is
one named combination of them. `MANAGING_SYSTEM` names the one to run; `python3 headless.py
--list-managing` prints them all.

| `--managing` | Analyse | Plan | Tuning | What it is for |
|---|---|---|---|---|
| `none` | — | — | — | no managing system at all: every UAV flies one policy for the whole run. The unmanaged baseline |
| `static` | `heuristic` | `static` | — | the loop runs and never reallocates. The **control arm** |
| `heuristic` | `heuristic` | `heuristic` | — | the default: base threat and crowding, damped by hysteresis |
| `defensive` | `cautious` | `defensive` | — | the base over everything else |
| `reactive` | `heuristic` | `heuristic` | hysteresis 1 | the default with the damping removed |
| `remote` | — | — | — | the whole loop on a server; see below |

`local` is still accepted and means `heuristic` — it was what the default managing system was called when
there was only one of it and the setting said where it ran rather than which it was.

`static` earns its place by being the arm that was missing. Turning the managing system on changes *two*
things at once: policies start being reallocated, **and** the team starts flying under `SuperPolicy`, whose
fleet wide traffic pass keeps UAVs off each other whatever they are flying. So a difference between `none`
and `heuristic` cannot be attributed to either. `static` runs the whole loop and plans no change, which
separates them:

```
--managing none        no SuperPolicy,  no adaptation      the simulation on its own
--managing static      SuperPolicy,     no adaptation      what SuperPolicy alone is worth
--managing heuristic   SuperPolicy,     adaptation         what the managing system is worth
```

### Adding one

One entry in `REGISTERED` in `sim/managing/systems.py`, naming the components it wants:

```python
ManagingSystemSpec(
    name="cautious-static",
    analyzer="cautious",
    planner="static",
    description="what it is for, which --list-managing and the web interface show",
)
```

It is then selectable from `config.py`, `headless.py --managing cautious-static` and the dropdown on the web
interface, and is covered by the parametrised tests in `tests/managing/test_systems.py` — which build every
registered system as they find it — without another line being written anywhere.

A new *component* is the same shape one level down: a `Planner` subclass with a unique `name` in
`sim/managing/plan/`, added to `PLANNERS` in that package's `__init__.py`. It then satisfies the contract
tests in `tests/managing/test_component_contract.py` automatically, the same way a new policy is picked up
by `tests/policy/test_policy_interface.py`.

For a combination worth trying but not worth naming, override the components of a registered system for one
batch:

```bash
python3 headless.py --managing heuristic --mape planner=defensive --mape analyzer=cautious
```

`ROLE` is one of `monitor`, `analyzer`, `planner`, `executor`, `knowledge`. A mistyped role or component
name stops the batch before the first run, listing what was available.

## Where the managing system lives

A managing system runs in this process or on a server, **as a whole**. That is its `location`, and it moves
the whole loop rather than one step of it: with `remote`, the analysis, the planning and the Knowledge base
are all over there.

`RemoteManagingSystem` presents the same surface as `ManagingSystem` — `tick()`, `adaptations()`, `name`,
`location`, a `knowledge` attribute — so the model, the runner and the web interface cannot tell them apart,
and none of them needed changing to support it.

**Local** is microseconds per evaluation, reproducible under `--seed`, works unchanged under
`headless.py --workers N`, and needs no network. Its weakness is that independence rests on the import
rule rather than on physics.

**Remote** makes the independence physical: a managing system on the other side of a socket cannot reach
into the simulation even by accident, because all it is ever given is the JSON below. It also stops being
Python — it can be a solver, another language, or a person at a dashboard. What it costs is a round trip
per evaluation (raise `ADAPTATION_PERIOD` to trade reaction speed for it), reproducibility that now depends
on the server too, and a set of failure modes that do not exist in-process.

One consequence worth being explicit about: **a quiet step still reaches the server.** A local managing
system stops after Analyse when nothing is wrong, and never plans. A remote one cannot, because deciding
that nothing needs doing is the server's decision to make — that is what makes it the managing system
rather than a remote helper the local side consults when it feels like it. So a remote managing system makes
one request per evaluation where a local one does work only on eventful ones.

### The remote contract

The client POSTs `application/json` to `MANAGING_SYSTEM_URL`:

```json
{
  "session": "3f9c1e02",
  "step": 37,
  "snapshot": { "step": 37, "grid_size": [50, 50],
                "uavs": [{"uav_id": 0, "pos": [7, 8], "alive": true, "hp": 3, "water": 1,
                          "policy": "firefighter", "params": {},
                          "fuel": 122.5, "fuel_capacity": 150.0,
                          "sees_fire": [[9, 9]], "sees_uavs": [[7, 9]], "sees_buildings": []}],
                "base": {"cells": [[5, 5]], "burning_steps": 1, "bhp": 5, "destroyed": false,
                         "serving": 0, "fire_near_base": [[6, 6]]} }
}
```

`snapshot` is the whole of what the sensor read, and there is no analysis in the request: working out what
is wrong is the server's job.

`session` identifies one run. A server keeping a Knowledge base between requests — which it must, to know
anything a single snapshot cannot tell it, such as whether the fire is closing on the base — has to key it
by this, because `headless.py --workers N` puts N runs in flight against one server at once.

The server answers `200` with:

```json
{
  "step": 37,
  "rationale": "base threat 2 (fire 1.4 cells off): 2 defend-base, 2 firefighter",
  "directives": [
    {"uav_id": 0, "policy": "defend-base", "params": {}},
    {"uav_id": 2, "policy": "disperse", "params": {"separation": 2, "speed_cap": 1}}
  ]
}
```

A UAV left out of `directives` keeps flying whatever it already was, so `"directives": []` means "nothing
to change" and a server that only wants to move one UAV sends one directive. `params` may be omitted.
Nothing in the response is trusted: it is parsed and then validated directive by directive by the effector,
which drops anything naming a UAV that does not exist, a UAV that has been destroyed, a policy that is not
registered, or a parameter outside its bounds.

**When the server is not there.** Every failure — connection refused, timeout, a 500, a body that is not
JSON, JSON that is not an allocation — is caught and logged, and then answered according to
`MANAGING_SYSTEM_FALLBACK`: `True` stands a local managing system in for that evaluation, so losing the
server costs the run its adaptation quality rather than its adaptation; `False` leaves the team on what it
was flying, which is the honest setting for an experiment about what a self-adaptive system does when its
managing system goes away. Either way the run completes — a run against a server that is not listening at
all finishes with the same results as `--managing heuristic`.

No server ships with this project. `sim/managing/remote.py` is the client and the contract; writing
something that answers it is the exercise.

## Running it

```bash
# what there is to choose from
python3 headless.py --list-managing

# the experiment the managing system exists for: the same fires, one arm per managing system
for m in none static heuristic defensive reactive; do
  python3 headless.py --runs 30 --workers 4 --seed 1 --policy firefighter --managing $m --output $m.json
done

# a combination that is not worth registering
python3 headless.py --managing heuristic --mape planner=defensive

# run the managing system on a server instead of in this process
python3 headless.py --managing remote --managing-url http://127.0.0.1:8600/manage
```

Same seeds mean the same fires, so the difference between two arms is the managing system. The results carry
`managing_system` and `managing_components` — which arm produced this file — alongside `adaptations`,
`policy_steps` (UAV-steps flown under each policy), `allocation_final`, `directives_rejected` and
`managing_failures`; the last two are zero on a healthy run and mean the result was produced with less
managing than was asked for.

On the web interface the sidebar gains a **Managing system** panel showing which managing system is running,
where it lives, what it is made of, how many adaptations there have been, what the team is flying right now
and its own one line account of why, and each UAV's line shows the policy it has been allocated.

### What it achieves

Measured, not asserted. Every arm uses identical seeds, so they all see identical fires.

**Goal (a), the home base.** 120 runs, `--seed 1`, 30×30 grid, 5 UAVs, `firefighter` baseline:

| `--managing` | base lost | base burn-steps | adaptations / run |
|---|---|---|---|
| `none` | 23 / 120 | 307 | — |
| `static` | 23 / 120 | 307 | 1 |
| `heuristic` | **14 / 120** | **233** | 36 |
| `defensive` | 16 / 120 | 267 | 31 |
| `reactive` | **14 / 120** | 289 | 29 |

**Goal (b), collisions.** 25 runs, `--seed 1`, 20×20 grid, 8 UAVs, `follow-fire` baseline — a policy with
no team level deconfliction of its own, on a grid crowded enough to need some:

| `--managing` | collisions | UAVs lost | base lost | base burn-steps |
|---|---|---|---|---|
| `none` | 155 | 125 | 25 / 25 | 125 |
| `static` | **0** | **0** | 25 / 25 | 125 |
| `heuristic` | **0** | **0** | **7 / 25** | **64** |

Read the two `static` rows together, because that arm is what makes the rest of the table interpretable.

* In (b) it removes **every** collision and saves **every** UAV while changing the base outcome not at all.
  So the collision result is entirely `SuperPolicy`'s fleet wide traffic pass, and none of it is adaptation
  — which the `none` versus `heuristic` comparison on its own could not have told you.
* In (a) it is byte for byte identical to `none`. Five UAVs on a 30×30 grid rarely come within
  `SECURITY_DISTANCE` of each other, so there is nothing for the traffic pass to do, and the whole of the
  9-run improvement is `defend-base` being allocated as the threat rises.

`defensive` defends earlier and with more of the team, and is slightly *worse* at both configurations than
the default. `reactive` matches it on bases lost while leaving the base burning longer. Neither is a
failure of the mechanism: they are the answers to two questions about how to manage this fleet, which is
what the registry exists to make askable.

Note that MR2 *rises* under management. It counts pairs of UAVs flying closer than `SECURITY_DISTANCE`,
un-normalised, so a run where the team survives 100 steps instead of being destroyed by step 30 has far
more pairs to count. Read it alongside `uavs_lost` rather than on its own.

# Common variables configuration

Every setting lives in `config.py`, which is organised into the same sections as this chapter and documents each variable and its bounds next to the value itself. This chapter is the longer form of the same information, followed by configuration examples for execution.

The bounds below are stated but hardly ever enforced: a value outside them usually still runs, and quietly gives nonsense. The few that raise an error are called out.

Any variable can also be overridden for a single run from the command line, without editing `config.py`:

```bash
python3 headless.py --set DENSITY_PROB=0.6 --set 'FIRE_START_POSITION=(3, 3)'
```

## Variables description

### Forest area

| Variable | Meaning | Bounds | Default |
|---|---|---|---|
| `BATCH_SIZE` | How long a run lasts, in time steps | integer `>= 1` | `100` |
| `WIDTH`, `HEIGHT` | Grid size (forest area size), in cells | integers `>= 1` | `60`, `60` |
| `FUEL_UPPER_LIMIT` | Most burnable fuel a cell can start with | integer `>= FUEL_BOTTOM_LIMIT`, and `> 0` | `10` |
| `FUEL_BOTTOM_LIMIT` | Least burnable fuel a cell can start with | integer, `1 <= it <= FUEL_UPPER_LIMIT` | `7` |
| `BURNING_RATE` | Fuel a burning cell loses per fire update | integer `>= 1` | `1` |
| `FIRE_SPREAD_SPEED` | Time steps between fire updates | integer `>= 1` | `2` |
| `DENSITY_PROB` | Share of the grid covered by vegetation | float in `[0, 1]` | `0.9` |

Each cell draws its fuel uniformly from `[FUEL_BOTTOM_LIMIT, FUEL_UPPER_LIMIT]` and burns for that many fire updates. `FUEL_UPPER_LIMIT` also scales the vegetation and fire colour ramps, so it has to stay above zero.

A larger `BURNING_RATE` burns cells out sooner, so the fire front is thinner and moves on faster; past `FUEL_UPPER_LIMIT` every cell burns out in a single update. A larger `FIRE_SPREAD_SPEED` means a slower spread, since everything else — the UAVs, the water drops, the immunity countdown — still runs every step. `0` raises `ZeroDivisionError`, and a fraction never satisfies the integer modulo in `Fire.step()`, which freezes the fire entirely.

`DENSITY_PROB` is rolled per cell: a cell without a Fire agent never burns, so `1` is a fully wooded map and `0` an empty one bar the ignition cell.

### Ignition

Where and when the initial wildfire starts. Both can be fixed or randomised.

`FIRE_START_POSITION`: the cell the fire starts from. Default `"random"`.

| Value      | Meaning                                                                       |
|------------|-------------------------------------------------------------------------------|
| `None`     | the centre of the grid                                                        |
| `"random"` | a uniformly random cell, never on the home base footprint                     |
| `(x, y)`   | that exact cell, which must lie inside the grid                               |

The ignition cell always holds a Fire agent, whatever `DENSITY_PROB` decides, so the fire has somewhere to start even on a sparse map.

`FIRE_START_STEP`: the simulation step the fire is lit at. Step 0 is the state the model is built in, so a fire lit at step 0 is already burning before the first step is taken. Default `(10, 20)`.

| Value      | Meaning                                                                        |
|------------|--------------------------------------------------------------------------------|
| `0`        | alight from the beginning of the run                                           |
| an `int`   | exactly that step, `>= 0`. A value `>= BATCH_SIZE` is warned about and never lights |
| `(a, b)`   | a random step drawn uniformly from the inclusive range `[a, b]`, with `0 <= a <= b` |
| `"random"` | a random step anywhere in the run, `[0, BATCH_SIZE)`                           |

Until that step nothing burns: the UAVs fly, MR2 accumulates, and MR1 stays at zero because there is nothing to monitor yet. The resolved cell and step are logged when the model is built, shown in the sidebar of the web interface, and recorded in the headless results as `fire_start_pos` and `fire_start_step`.

To try either from the command line, without editing `config.py`:

```bash
# a random cell, lit somewhere between steps 5 and 20
python3 headless.py --runs 5 --seed 1 --set FIRE_START_POSITION=random --set 'FIRE_START_STEP=(5, 20)'

# a specific corner, lit at step 10
python3 headless.py --set 'FIRE_START_POSITION=(3, 3)' --set FIRE_START_STEP=10
```

### Wind

Wind raises the chance of the fire spreading downwind and lowers it upwind, by a fraction `MU` of the probability that is left. All of it is ignored unless `ACTIVATE_WIND` is `True`.

| Variable | Meaning | Bounds | Default |
|---|---|---|---|
| `ACTIVATE_WIND` | Whether the fire spread is influenced by wind | `True` / `False` | `False` |
| `FIXED_WIND` | Whether the wind blows from one direction or two | `True` / `False` | `False` |
| `WIND_DIRECTION` | The single direction, used when `FIXED_WIND` is `True` | `'north'`, `'south'`, `'east'`, `'west'` | `'south'` |
| `FIRST_DIR` | Predominant direction of a composed wind | `'north'`, `'south'`, `'east'`, `'west'` | `'south'` |
| `SECOND_DIR` | The other direction, blown whenever the first is not | `'north'`, `'south'`, `'east'`, `'west'` | `'east'` |
| `FIRST_DIR_PROB` | How far `FIRST_DIR` predominates | float in `[0, 1]` | `0.8` |
| `MU` | Wind strength (wind velocity) | float in `[0, 1]` | `0.9` |
| `PROBABILITY_MAP` | Draw each cell's probability of catching fire instead of the forest | `True` / `False` | `False` |

`FIRST_DIR`, `SECOND_DIR` and `FIRST_DIR_PROB` only exist when `FIXED_WIND` is `False`, which is also the only time anything reads them. Mixing two perpendicular directions gives a diagonal wind: NW, NE, SW or SE. `FIRST_DIR_PROB` is drawn afresh per cell per update, so `1` collapses onto `FIRST_DIR`, `0` onto `SECOND_DIR`, and `0.5` splits the wind evenly. A direction outside the four raises `ValueError` in `fire_spread.build_kernel()`.

`MU = 0` makes the wind irrelevant and `MU = 1` makes it absolute.

`PROBABILITY_MAP` requires `NUM_AGENTS = 0`: nothing but the fire is drawn on the probability map, so a UAV would be handed a portrayal with no `"Layer"` attribute and the canvas would throw `KeyError: 'Layer'`.

### Smoke

| Variable | Meaning | Bounds | Default |
|---|---|---|---|
| `ACTIVATE_SMOKE` | Whether smoke is part of the simulation | `True` / `False` | `False` |
| `SMOKE_PRE_DISPELLING_COUNTER` | Steps between a cell catching fire and its smoke appearing | integer `>= 0` | `2` |

The smoke then lasts for the cell's initial fuel, set as `self.dispelling_counter_start_value` in `Smoke.__init__()` in `sim/environment.py`. Keep the sum of the two above `FUEL_UPPER_LIMIT`, or the smoke clears before the cell has finished burning.

### UAV

| Variable | Meaning | Bounds | Default |
|---|---|---|---|
| `NUM_AGENTS` | UAVs flying over the forest area | integer `>= 0`, and `<= WIDTH * HEIGHT` | `10` |
| `N_ACTIONS` | Size of the movement action space a policy draws from | `4`, or `5` to include `ACTION_STAY` | `4` |
| `UAV_SPEED` | Most cells a UAV can cover in one time step | integer `>= 0` | `5` |
| `UAV_OBSERVATION_RADIUS` | How far a UAV sees, in cells | integer `>= 0` | `4` |
| `SECURITY_DISTANCE` | Separation, in cells, the team is meant to keep | number `>= 0` | `10` |
| `UAV_HP` | Health points each UAV starts with | integer `>= 1` | `3` |
| `UAV_COLLISION_DAMAGE_MEAN` | Average health points a collision costs one UAV | float in `[0, 1]`, clamped | `1.0` |

`NUM_AGENTS = 0` simulates the wildfire spread on its own, and is required when `PROBABILITY_MAP` is on. The upper bound is the size of the grid, because the team is launched unstacked.

`N_ACTIONS` covers the four movement directions `[north, east, west, south]`, indices `0..3`. Holding position (`ACTION_STAY`) and dumping water (`ACTION_DUMP_WATER`) sit outside the space on purpose, so that the random baseline keeps drawing from the original four; raise it to `5` to bring holding position into the action space of a learning algorithm.

`UAV_SPEED` is the ceiling on one step of flight. A policy returns a direction and a speed for each UAV (for example north at speed 3), and the UAV flies up to that many cells along that direction, stopping early at the edge of the grid, or on the cell of another UAV it has flown into. Set it to `1` for the original one cell per step behaviour, or to `0` to ground the fleet.

`UAV_OBSERVATION_RADIUS` is not really a radius, since observed areas are the square of side `2 * radius + 1` centred on the UAV. A radius below `UAV_SPEED` lets a UAV fly past what it can see, and so into teammates it was never told were there.

`SECURITY_DISTANCE` is a **scoring heuristic only**: `MR2` counts the pairs of UAVs that are closer than this to each other on each step, which measures how much collision risk a policy accepts. It does not stop a UAV from flying anywhere, and it is not what decides whether two UAVs have collided—see the health points below. `0` never scores; a value larger than the grid diagonal scores every pair on every step.

#### Health points and collisions

Two or more UAVs that end a time step **on the same cell** have collided. Each of them then rolls for damage, and a UAV whose health points reach zero is destroyed: it is taken off the grid and out of the scheduler, stops observing, acting and scoring `MR1`, and takes no further part in the run. The rest of the team carries on, and the run itself continues even if the whole fleet is lost.

The **home base is shared airspace**: any number of UAVs can sit on its footprint without colliding, which is what lets the whole team start there and queue on it to refill. Flying over the base does not stop a UAV either. Everywhere else, a UAV that flies into an occupied cell takes that cell and its flight ends there, rather than passing over it.

Collisions are settled once per step, from where the UAVs ended up, so the damage does not depend on the order the scheduler happened to move them in, and two UAVs left stacked on one cell keep paying for it every step until they separate or are destroyed.

`UAV_HP`: Health points each UAV starts the run with. Set it high enough that collisions cost a policy something without ending its run outright, or to a very large number to study a fleet that cannot be destroyed.

`UAV_COLLISION_DAMAGE_MEAN`: **Average** health points a UAV loses for a step spent sharing a cell with another one. The damage is rolled once per UAV per collision and is either a whole health point or nothing at all, so health points stay whole numbers while the expected cost of a collision is this value:

| value | effect |
| --- | --- |
| `1.0` | a full health point every time — the default, and a certain loss |
| `0.5` | half the collisions cost a point, half do no harm |
| `0.25` | one health point in four collisions on average |
| `0.0` | collisions are still counted and logged, but never damage anybody |

Anything outside `[0, 1]` is clamped, because a collision can never cost more than one health point. The roll is `config.roll_collision_damage()`, and it draws from `SYSTEM_RANDOM`, so a seeded run reproduces it exactly.

Two UAVs involved in one collision roll independently: one can be destroyed while the other walks away. The `Collisions` counter reports the collisions themselves rather than the damage they did, so a run with a low mean still shows how often the team flew into itself; the log records what each UAV actually lost:

```
collision at (24, 2) between UAVs [3235, 3236], health points lost: {3235: 1, 3236: 0}
```

The graphical interface reports the health of every UAV on its own line of the sidebar, in figures that turn amber and then red as it drops, and marks a destroyed one as `destroyed`. The `Collisions` counter beside the metrics is how many times a cell was found holding more than one UAV; `headless.py` records the same as `collisions` and `uavs_lost` in its results.

### Fuel extension

An optional extension that gives each UAV a tank to fly on. It is switched off by default; with `ACTIVATE_FUEL = False` nothing in this section is burned, tracked or reported, and the simulator behaves exactly as it did before the extension existed.

> Note that **"fuel" means two unrelated things** in this project. `FUEL_UPPER_LIMIT` and `FUEL_BOTTOM_LIMIT` in the forest area section are how much a *vegetation cell* has left to burn. Everything here is the fuel in a *UAV's tank*, and the two never interact.

A UAV that runs its tank dry **loses every health point it has left and is destroyed**, exactly as a fatal collision destroys it: off the grid, out of the scheduler, no further part in the run. It is settled once per step, after the collisions, so a UAV that both collided fatally and ran dry on the same step is counted once, against the collision.

#### What a step costs

```
cost = idle + UAV_FUEL_BURN_PER_CELL * cells_moved ** UAV_FUEL_SPEED_EXPONENT
```

The **idle burn** is charged for staying in the air at all, so holding position and dumping water are cheap but not free. It is waived for a UAV parked on the home base footprint — engines off — which is what makes flying home worth the trip.

`cells_moved` is the distance **actually covered**, so a UAV stopped early by the edge of the grid or by another UAV pays only for the flight it really made.

Because the exponent is above `1`, **each extra cell of speed costs more than the last**, the way the power a real airframe draws climbs steeply with airspeed. Covering ground in one fast dash costs more than covering it slowly, which gives a policy a genuine reason to cruise:

| flight | fuel at the defaults |
| --- | --- |
| hold position | `1.0` |
| 1 cell | `2.0` |
| 3 cells in one step | `6.2` |
| 5 cells in one step | `12.2` |
| 5 cells, one per step over 5 steps | `10.0` |

`ACTIVATE_FUEL`: Master switch for the extension.

`UAV_FUEL`: Units in a full tank, which is what every UAV starts the run with. Size it against `BATCH_SIZE` and how many sorties a run should allow: at the defaults, holding position costs `1` a step and cruising three cells a step costs about `6.2`, so a 150 unit tank is either 150 steps of loitering or about 24 of cruising.

`UAV_FUEL_IDLE_BURN`: Fuel burned per step spent airborne, whatever the UAV did. `0` lets a UAV loiter for free, so only distance costs.

`UAV_FUEL_BURN_PER_CELL`: Fuel burned per cell of flight, before the speed penalty. `0` makes movement free, leaving the idle burn as a pure clock.

`UAV_FUEL_SPEED_EXPONENT`: How much harder each extra cell of speed is on the tank. `1.0` is flat, so five cells cost five times one cell however they are flown; `1.5` is the default; `2.0` makes sprinting a serious decision. Below `1` it rewards sprinting instead, which is not physical but is a legitimate thing to experiment with.

`UAV_FUEL_RESERVE`: The share of a tank at or below which a policy should turn for home. **Advisory only** — nothing in the simulation enforces it. `Observation.low_fuel()` reports it, and the `firefighter` policy acts on it.

`BASE_REFUEL_STEPS`: Steps a UAV must spend at the base to fill its tank.

#### Refuelling

Refuelling happens at the **home base**, so it needs the firefighting extension switched on as well. With fuel on and `ACTIVATE_FIREFIGHTING = False` there is nowhere to refuel, which turns `UAV_FUEL` into a hard endurance limit on the whole run — a legitimate way to ask how much a policy achieves before its fleet is gone.

Refuelling is not an action, and it **shares the refilling slot with water**: a UAV standing on the base that wants either takes one of the `BASE_CAPACITY` slots, waits `max(BASE_REFILL_STEPS, BASE_REFUEL_STEPS)` steps, and gets a full load of water and a full tank together. A UAV that is full of water but short of fuel is a reason to be served, so it can make a thirsty teammate queue — the base is deliberately the one logistics bottleneck.

#### What a policy is told

An `Observation` carries `fuel` and `fuel_capacity`, both `None` when the extension is off, which is what tells a policy fuel is not being tracked at all rather than that the tank is empty. Two helpers read them:

```python
observation.fuel_fraction()   # how much of a full tank is left, 1.0 when fuel is not tracked
observation.low_fuel()        # at or below UAV_FUEL_RESERVE; always False when fuel is not tracked
```

The `firefighter` policy acts on the reserve: a UAV down to it breaks off whatever it was doing, flies home with its water still aboard, and **waits on the base until the tank is full** — landing is not enough, since a visit takes `BASE_REFUEL_STEPS`. The reserve is a flat share of the tank, not an estimate of the fuel needed to reach the base, so a UAV that strays far enough from home can still run dry on the way back; sizing the reserve against how far the team ranges is left to whoever configures the run. `random` and `follow-fire` take no notice of fuel at all and will fly themselves into the ground.

The sidebar shows each UAV's tank beside its health, in figures that turn amber and then red as it empties. `headless.py` records `uavs_out_of_fuel` and `fuel_remaining` in its results, and logs a `fuel |` line per run:

```
fuel | ran dry=0/4 | tanks left: mean=31.6 min=24.8 of 40
```

To try it from the command line, without editing `config.py`:

```bash
python3 headless.py --steps 60 --policy firefighter --set ACTIVATE_FUEL=True --set UAV_FUEL=40
```

### Firefighting extension

An optional extension that turns the simulation into a firefighting scenario. It is switched off by default; with `ACTIVATE_FIREFIGHTING = False` every variable in this section is ignored and the simulator behaves exactly as it did before the extension existed.

When it is switched on:

<ul>
  <li>a <b>home base</b> is placed on the map, drawn in blue, and every UAV starts from it;</li>
  <li>each UAV carries one <b>load of water</b>, and is drawn full size while it still has it, shrinking to a smaller square once it has dropped it;</li>
  <li>a UAV can <b>dump its water</b>, extinguishing the fire under it and around it;</li>
  <li>extinguished cells are drawn in light blue, are immune for a while, and can then <b>re-ignite</b>;</li>
  <li><b>out buildings</b> are scattered over the map, drawn in brown, and turn dark grey once they burn down;</li>
  <li>the run is <b>lost</b> if the home base burns for too long.</li>
</ul>

| Variable | Meaning | Bounds | Default |
|---|---|---|---|
| `ACTIVATE_FIREFIGHTING` | Master switch for the whole extension | `True` / `False` | `True` |
| `BASE_POSITION` | Cell the home base is anchored on | `(x, y)` inside the grid, or `None` | `None` |
| `BASE_SIZE` | Footprint of the base, as `(width, height)` | pair of integers `>= 1` | `(2, 2)` |
| `BHP` | Base health points | integer `>= 1` | `5` |
| `BASE_REFILL_STEPS` | Steps a UAV must spend at the base to refill | integer `>= 1` | `1` |
| `BASE_CAPACITY` | UAVs that can refill at the same time | integer `>= 1` | `1` |
| `UAV_WATER_CAPACITY` | Loads of water a UAV can carry at once | integer `>= 1` | `1` |
| `WATER_DROP_RADIUS` | How far a drop reaches, in cells | integer `>= 0` | `2` |
| `WATER_EXTINGUISH_PROB_CENTRE` | Chance of extinguishing the cell under the drop | float in `[0, 1]` | `0.95` |
| `WATER_EXTINGUISH_PROB_EDGE` | Chance of extinguishing a cell at `WATER_DROP_RADIUS` | float in `[0, 1]` | `0.60` |
| `REIGNITION_DELAY` | Steps an extinguished cell is immune | integer `>= 0` | `8` |
| `SPONTANEOUS_REIGNITION_PROB` | Per step chance an extinguished cell relights on its own | float in `[0, 1]`, keep low | `0.005` |
| `NUM_OUT_BUILDINGS` | Out buildings scattered over the map | integer `>= 0` | `0` |
| `OUT_BUILDING_HP` | Steps an out building survives while its cell burns | integer `>= 1` | `5` |

`BASE_POSITION` is the bottom left corner of the footprint; `None` places the base a quarter of the way into the grid. The default deliberately avoids the centre, because that is where the initial fire is lit by default, so putting the base there means it burns from the first step. A position outside the grid raises `ValueError`.

`BASE_SIZE` gives a footprint that is drawn blue in full, burns, and can be refilled from anywhere on it, clipped to the grid at the edges. The team is spread over it at the start of a run, one UAV per cell in order, so that the fleet is visible on the map from the first step instead of being stacked on one cell, and does not launch on top of itself. A team that outnumbers the footprint spills over into the cells around the base, nearest ring first and at random within each ring; a team larger than the whole grid is refused, because there is no way to launch it unstacked.

`BHP` is spent one step at a time: the run is lost once the base cells have burned for that many steps in total. The damage is cumulative rather than consecutive, because a burning cell goes out for a step when none of its neighbours are alight yet, so the base collects its damage over several visits from the fire.

`BASE_REFILL_STEPS` counts the steps a UAV has to spend on the base to take on a load of water. Refilling is not an action: a UAV with an empty tank standing on the base starts refilling by itself. `0` behaves the same as `1`, since a refill still takes the step it starts on. `BASE_CAPACITY` of `1`, the requirement, means UAVs arriving together have to queue.

A water drop covers a disc, so the corners of the surrounding square are outside it, and `WATER_DROP_RADIUS = 0` wets only the target cell. Between the centre and the radius the probability falls off linearly with the distance; beyond the radius it is zero. Centre is normally the larger of the two probabilities, though the reverse is allowed and simply makes the drop stronger at its rim.

`REIGNITION_DELAY` of `0` lets a cell relight the step after it was doused. `SPONTANEOUS_REIGNITION_PROB` is rolled for every cell that was extinguished at some point and still has fuel, on every step, which is why it should stay small.

Out buildings are never placed on the home base, and if more are asked for than there are free cells, only what fits is placed.

The `firefighter` policy in `sim/policy/firefighter.py` is written for this extension: it carries water to the fire, prefers fires that threaten an out building, dumps its load once in range, and flies back to the base to refill. It also keeps its team apart, sending no two UAVs to the same fire or through the same cell, so that it does not destroy its own fleet in collisions. The other policies still run with the extension switched on, but never dump water, since `ACTION_DUMP_WATER` sits outside `N_ACTIONS` and is only emitted by policies that opt in; `random` and `follow-fire` take no care to avoid each other either, so they lose UAVs to collisions.

Because this extension is what gives a run something to lose, `headless.py` reports every run as **WON** or **LOST** while it is switched on, and the batch summary gives the share of runs that were lost:

```
firefighting | drops=12 extinguished=31 refills=4 | out buildings destroyed=1/6
RUN LOST | home base burned 5/5 step(s)
...
outcome     : 3 WON, 1 LOST of 4 run(s) | lost proportion=25.0%
out buildings destroyed: mean=1.00 min=0 max=3 of 6 placed
```

The out building figures only appear when `NUM_OUT_BUILDINGS` actually placed some, and the outcome lines only when `ACTIVATE_FIREFIGHTING` is on, since without a home base there is nothing to lose. The results record `lost`, `buildings_lost`, `buildings_total` and `base_burning_steps` per run, plus `outcome` as the `WON`/`LOST`/`N/A` string.

To try it from the command line, without editing `config.py`:

```bash
python3 headless.py --policy firefighter --set ACTIVATE_FIREFIGHTING=True
```

### Managing system

Optional, and ignored entirely when `MANAGING_SYSTEM` is `'none'`. See
[The managing system](#the-managing-system) for what these do.

| Variable | Meaning | Bounds |
|---|---|---|
| `MANAGING_SYSTEM` | which MAPE-K managing system runs over the simulation. The starting value only: the web interface's `Managing system` dropdown and `headless.py --managing` both override it per run | a name registered in `sim/managing/systems.py`; `python3 headless.py --list-managing` prints them |
| `ADAPTATION_PERIOD` | simulation steps between runs of the loop; larger is cheaper and slower to react. A managing system may state its own, as `reactive` does | integer `>= 1` |
| `ADAPTATION_HYSTERESIS` | consecutive evaluations that must agree before a UAV's policy is changed; `1` disables the damping, which is what `reactive` does by stating its own | integer `>= 1` |
| `DEFAULT_UAV_POLICY` | the policy a local planner treats as normal, what an unallocated UAV flies, and what the team starts under | a registered policy name |
| `BASE_SENSOR_RADIUS` | how far around the base the managing system sees the ground truth; `0` leaves it with only the UAV reports | integer `>= 0` |
| `BASE_THREAT_RADIUS` | how close fire must get to the base to count as threatening it | integer `>= 1` |
| `MANAGING_CROWDED_SPEED_CAP` | speed a UAV is held to while being moved out of a crowd | integer `>= 0` |
| `MANAGING_KNOWLEDGE_HISTORY` | how many past snapshots the Knowledge base keeps | integer `>= 1` |
| `MANAGING_SYSTEM_URL` | where a remote managing system lives; read only when `MANAGING_SYSTEM` is `'remote'` | an http(s) URL |
| `MANAGING_SYSTEM_TIMEOUT` | seconds to wait for a remote managing system before giving up on it | float `> 0` |
| `MANAGING_SYSTEM_FALLBACK` | whether an unreachable remote managing system is stood in for locally. `False` leaves the team on what it was flying, which is the honest setting for studying what happens when a managing system goes away | `True` / `False` |

`DEFAULT_UAV_POLICY` is checked for being a name here and resolved when the model is built, because
`config.py` cannot import the policy package — the policy package imports `config.py`. An unknown name
raises a `KeyError` listing the policies that do exist.

### Colours

The last section of `config.py` is presentation only: it changes what the web interface draws, never what the simulation does. Every entry is a CSS colour string, `"#rrggbb"`.

The map is kept light on purpose. Everything that has to be found at a glance — the UAVs, the home base, the out buildings — is drawn dark and small over a background of vegetation that covers most of the grid, so the darker that background is the harder those things are to pick out.

`VEGETATION_COLORS` and `FIRE_COLORS` are ramps indexed by the fuel a cell has left and must be the same length, which `COLORS_LEN` takes from the first of them; index 0 of both is a burnt out cell, which is why the two share `BURNT_COLOR`. `SMOKE_COLORS` only ever uses its first entry. `BLACK_AND_WHITE_COLORS` is the ramp for `PROBABILITY_MAP`, indexed by the probability rounded to one decimal, so it needs exactly 11 entries.

## Configuration examples

Six default examples of how different variables can be configured to develop distinct scenarios, can be seen below. All scenarios shown are captured in `time step = 20`, in different time steps scenarios might look different.

### Common default variables

Before showing the examples, this section compiles all variables that can be set in common with all examples. The variables that were not mentioned can be set to their default value.

`BATCH_SIZE = 90`

`WIDTH = 50`, `HEIGHT = 50`

`BURNING_RATE = 1`

`FIRE_SPREAD_SPEED = 2`

`FUEL_UPPER_LIMIT = 10`, `FUEL_BOTTOM_LIMIT = 7`

`DENSITY_PROB = 1`

### Normal conditions (no smoke, no wind, no UAV)

A scenario with no wind, smoke, or UAV, should appear.

`NUM_AGENTS = 0`

`ACTIVATE_WIND = False`

`ACTIVATE_SMOKE = False`

`PROBABILITY_MAP = False`

### Windy conditions (no smoke, wind, no UAV)

Concretely, a scenario with two weak wind components should appear, first with 50% of south component, and a second west component with 50%. In this scenario, neither smoke nor UAV should appear.

`NUM_AGENTS = 0`

`ACTIVATE_WIND = True`

`ACTIVATE_SMOKE = False`

`PROBABILITY_MAP = False`

`FIXED_WIND = False`

`WIND_DIRECTION = 'south'`

`FIRST_DIR = 'south'`

`SECOND_DIR = 'west'`

`FIRST_DIR_PROB = 0.5`

`MU = 0.5`

### Windy and partial observabiliy conditions (smoke, wind, no UAV)

A scenario with strong windy conditions, blowing east, and late short-lasting smoke should appear. Remember that, since the dispelling counter for smoke is set in `Smoke` class by default, inside `sim/environment.py`, changes should be done to the `self.dispelling_counter_start_value` variable, inside `__init()__` method (`Smoke` class). Keep also in mind that `self.dispelling_counter_start_value + SMOKE_PRE_DISPELLING_COUNTER` should be greater than the amount of fuel assigned to each cell (for taking less risks, compare to `FUEL_UPPER_LIMIT`, which is the maximum possible amount of fuel of each cell), in order to avoid situations in which smoke dissipates before the end of the cell’s burning process.

`NUM_AGENTS = 0`

`ACTIVATE_WIND = True`

`ACTIVATE_SMOKE = True`

`PROBABILITY_MAP = False`

`FIXED_WIND = True`

`WIND_DIRECTION = 'east'`

`MU = 0.95`

`SMOKE_PRE_DISPELLING_COUNTER = 7`

`self.dispelling_counter_start_value = 4`

### 2 UAV with small partial areas (normal conditions)

A scenario with 2 UAV having small partial areas in normal conditions should appear.

`NUM_AGENTS = 2`

`ACTIVATE_WIND = False`

`ACTIVATE_SMOKE = False`

`PROBABILITY_MAP = False`

`UAV_OBSERVATION_RADIUS = 3`

### 3 UAV with big partial areas (smoke, no wind)

A scenario with 3 UAV having big partial areas, with fast long-lasting smoke, should appear.

`NUM_AGENTS = 3`

`ACTIVATE_WIND = False`

`ACTIVATE_SMOKE = True`

`PROBABILITY_MAP = False`

`SMOKE_PRE_DISPELLING_COUNTER = 2`

`self.dispelling_counter_start_value = 9`

`UAV_OBSERVATION_RADIUS = 12`

### Probabaility map

A scenario with normal conditions should appear. Keep in mind that changing wind conditions will affect to the visualized probabilitites. Also, remember to set 0 UAV when showing the fire probability map.

`NUM_AGENTS = 0`

`ACTIVATE_WIND = False`

`ACTIVATE_SMOKE = False`

`PROBABILITY_MAP = True`
