# Project overview

## Project description

Wildfire-UAVSim is a customizable wildfire tracking simulator that enables
the evaluation of diverse adaptation strategies. Among its many configuration parameters, the forest area is customizable with different densities of vegetation, as well as fire and smoke dispersion patterns that are affected by factors such as wind, conforming different observability conditions. The configuration options of our simulator also allow to place a team of UAVs in charge of tracking the fire over the forest area. Wildfire-UAVSim provides a graphical web interface native from Mesa framework, executed by the simulator, in order to keep track of how the simulation evolves in time.

## Files structure

The project structure is composed of the following Python files and packages:

### `agents.py`

This python file holds the logic for managing elements such as Fire, Smoke, Wind and UAVs.

### `widlfire_model.py`

This python file holds the logic for managing the wildfire simulation, by utilizing elements from `agents.py` file.

### `fire_spread.py`

This python file works out how likely every cell of the grid is to catch fire, for the whole grid at
once, and is by far the largest influence on how fast a simulation runs.

The rule itself is unchanged, and is still written out cell by cell in `Fire.probability_of_fire()`
in `agents.py`. That version asks each cell to walk its neighbourhood, which repeats the same
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

### `main.py`

This python file allows to execute the wildfire simulation built in `widlfire_model.py` file.

### `config.py`

This python file holds the variables used to set the simulation execution configurations. It is organised into sections in the order a run is built up — the environment, the forest, the ignition, the wind, the smoke, the UAVs, the firefighting extension, the drawing colours and a few shared helper functions — and each variable carries a one line description and its bounds next to its value. [Common variables configuration](#common-variables-configuration) below is the longer form of the same material.

### `Canvas_Grid_Visualization.py`

This python file contains a Mesa class, modified for making UAV observation areas visible on the graphical web interface. It is not really necessary to change this file.

### `policy/`

This python package holds the policies that decide where each UAV flies. `policy/base.py` defines the abstract `Policy` interface, `policy/observation.py` defines the `Observation` a UAV receives, `policy/action.py` defines the `Action` it returns, and every concrete policy lives in its own file (`policy/random_policy.py`, `policy/follow_fire.py`). The policy in use can be picked from the dropdown on the web interface, or with the `--policy` option of `headless.py`.

A policy receives one `Observation` per UAV and returns one `Action` per UAV: a direction and a speed.

```python
from policy import Action, Policy
from config import ACTION_UP

class MyPolicy(Policy):
    name = "my-policy"

    def select_actions(self, observations):
        # every UAV flies three cells north, whatever it sees
        return [Action(ACTION_UP, 3) for _ in observations]
```

`Action.stay()` holds position and `Action.dump()` drops water; both carry a speed of zero. A UAV never covers more than `UAV_SPEED` cells in a step, whatever speed is asked for, and stops early at the edge of the grid. A policy may also return a bare direction index, or a `(direction, speed)` pair, which are coerced into an `Action` — a bare direction means one cell per step, as it did before speeds existed.

An `Observation` reports what one UAV can see: `pos`, the `cells` in view with their burning state, and `uav_positions`, the cells the **other UAVs in view** are standing on. Flying onto one of those is a collision and costs both UAVs health points, so a policy that moves its team about has to keep it apart. Three helpers in `policy/base.py` are there for that:

```python
from policy import avoid, flight_path, by_distance

flight_path(pos, action)          # the cells the action would take the UAV through, in order
avoid(pos, action, blocked)       # the same action, trimmed to stop short of any 'blocked' cell
by_distance(pos, positions)       # positions ordered nearest first, for picking an unclaimed target
```

`FirefighterPolicy` shows the pattern: it claims a fire per UAV so that no two are sent to the same cell, then trims each action with `avoid()` so that no UAV flies into one it can see or lands where a teammate has already been sent. The cells of the home base are deliberately left out of `blocked` — `observation.base_footprint()` reports them — because UAVs do not collide there and must be able to land to refill.

It also never asks a UAV to fly further than `UAV_OBSERVATION_RADIUS`. This matters whenever `UAV_SPEED` is the larger of the two, as it is by default (`5` against `4`): a flight that ends outside the observation window lands on a cell `uav_positions` said nothing about, so the UAV can fly into a teammate it was never told was there. Giving up the last cell of speed is cheaper than the collision.

With the firefighting extension on, an `Observation` also carries `has_water`, `base_pos`, `base_cells` and `building_positions`; `at_base()` is true anywhere on the base footprint. With the fuel extension on it carries `fuel` and `fuel_capacity`, read through `fuel_fraction()` and `low_fuel()`; both are `None` when fuel is not being tracked, and `low_fuel()` is then always `False`, so a policy that ignores fuel flies exactly as it did before.

### `headless.py`

This python file runs simulations without the graphical interface, with logging and optional parallel execution. Run `python3 headless.py --help` for the available options.

### `tests/`

This directory holds the unit tests. See [Running the tests](#running-the-tests).

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

# Running the tests

The unit tests live in the `tests/` directory and are run with [pytest](https://docs.pytest.org/). They cover the UAV policies in the `policy/` package, and need neither a grid nor the Mesa framework, so the whole suite finishes in well under a second.

## From the command line

From the root of the project:

```bash
python3 -m pytest
```

Useful variations:

```bash
python3 -m pytest tests/test_follow_fire_policy.py   # a single file
python3 -m pytest -k "holds_position"                # tests whose name matches a pattern
python3 -m pytest -q                                 # quiet, one line per file
python3 -m pytest -x                                 # stop at the first failure
```

Test discovery is configured in `pytest.ini`, which also puts the project root on the import path so that `import policy` and `import config` work from inside `tests/`.

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

The contract tests in `tests/test_policy_interface.py` are parametrised over every policy in the registry, so a newly registered policy is automatically checked for returning one valid `Action` per UAV, keeping its speeds within `UAV_SPEED`, handling an empty view, and having a usable name.

Tests about the movement itself — how far a UAV actually gets — need a grid, and live in `tests/test_uav_speed.py`.

# Graphical interface functionalities

When executing the project as explained above, a web page hosted in http://127.0.0.1:8521/ should appear in user's default browser. Port can be modified in `main.py` file if user has the default one already busy.

Everything used to drive a run sits in the bar along the top of the page: the speed slider, the step the run has reached, and the buttons. The status panel is down the left hand side, and the policy in use is picked above the grid on the right. The relevant graphical interface elements are:

### `Grid`

The grid with generated cells, with vegetation, fire, smoke, and UAVs, can be seen in the center of the screen.

### `Start button`

The start button allows to run the simulation without stopping. It becomes `Stop` while the simulation is running, and `Done` once the run has reached `BATCH_SIZE` steps.

### `Step button`

The step button allows to execute one time step at a time.

### `Reset button`

The reset button allows to execute the `reset()` method, inherited and overwritten from Mesa framework class `mesa.Model`, into WildFireModel class, inside `widlfire_model.py` file.

### `FPS`

It is a slider that allows to set the frames per second (FPS) velocity for the graphical visualization of the simulation execution. Each frame corresponds to one time step. Its range goes from 1 to 20 FPS, taking into account that, counterintuitively, 0 FPS set the fastest FPS velocity. One reason why the simulation might seem not be playing fluently could be the setting of the `FIRE_SPREAD_SPEED` variable referenced below.

### `Step counter`

Indicates the current time step of the simulation, beside the buttons that advance it.

### `Status panel`

The panel down the left hand side reports the monitoring metrics, the state of the home base and the out buildings, and a line per UAV with its position, its health and the water it is carrying. Figures turn amber and then red as whatever they measure is used up.

### `UAV policy`

The dropdown above the grid picks the rule that decides where each UAV flies. Press `Reset` after changing it to restart the simulation with the new policy.

### `Colours`

The map is deliberately kept light. Vegetation runs from near white to a mid green, and the fire from pale yellow to a bright red orange, so that the things worth finding at a glance stay the darkest marks on it: the UAVs are near black, the home base is a deep blue block, and the out buildings are brown. A UAV is outlined in white, which is what keeps it visible on the two backgrounds as dark as it is — the base and burnt ground — and the square marking what it can see is drawn in a lighter slate, so that a team of any size does not bury the map under its own observation windows. All of it is in the `Colours` section of `config.py`.

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

The smoke then lasts for the cell's initial fuel, set as `self.dispelling_counter_start_value` in `Smoke.__init__()` in `agents.py`. Keep the sum of the two above `FUEL_UPPER_LIMIT`, or the smoke clears before the cell has finished burning.

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

The `firefighter` policy in `policy/firefighter.py` is written for this extension: it carries water to the fire, prefers fires that threaten an out building, dumps its load once in range, and flies back to the base to refill. It also keeps its team apart, sending no two UAVs to the same fire or through the same cell, so that it does not destroy its own fleet in collisions. The other policies still run with the extension switched on, but never dump water, since `ACTION_DUMP_WATER` sits outside `N_ACTIONS` and is only emitted by policies that opt in; `random` and `follow-fire` take no care to avoid each other either, so they lose UAVs to collisions.

To try it from the command line, without editing `config.py`:

```bash
python3 headless.py --policy firefighter --set ACTIVATE_FIREFIGHTING=True
```

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

A scenario with strong windy conditions, blowing east, and late short-lasting smoke should appear. Remember that, since the dispelling counter for smoke is set in `Smoke` class by default, inside `agents.py` file, changes should be done to the `self.dispelling_counter_start_value` variable, inside `__init()__` method (`Smoke` class). Keep also in mind that `self.dispelling_counter_start_value + SMOKE_PRE_DISPELLING_COUNTER` should be greater than the amount of fuel assigned to each cell (for taking less risks, compare to `FUEL_UPPER_LIMIT`, which is the maximum possible amount of fuel of each cell), in order to avoid situations in which smoke dissipates before the end of the cell’s burning process.

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
