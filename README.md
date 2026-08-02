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

This python file holds the variables used to set the simulation execution configurations.

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

With the firefighting extension on, an `Observation` also carries `has_water`, `base_pos`, `base_cells` and `building_positions`; `at_base()` is true anywhere on the base footprint.

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

`pos` is where the UAV is, `burning` and `unburnt` are the cells it can see; cells outside its observation radius are simply left out. `uavs=[(5, 7)]` puts other UAVs in view, for testing that a policy keeps its team apart. The `uav_speed` fixture pins `UAV_SPEED` for the test, so an expected speed does not depend on what `config.py` is set to. For a policy that makes random choices, the `seed_rng` fixture replaces `config.SYSTEM_RANDOM` with a seeded generator so the result is reproducible:

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

The relevant graphical interface elements are:

### `Grid`

The grid with generated cells, with vegetation, fire, smoke, and UAVs, can be seen in the center of the screen.

### `Start button`

The start button allows to run the simulation without stopping.

### `Step button`

The step button allows to execute one time step at a time.

### `Reset button`

The reset button allows to execute the `reset()` method, inherited and overwritten from Mesa framework class `mesa.Model`, into WildFireModel class, inside `widlfire_model.py` file.

### `Frames per second`

It is a slider that allows to set the frames per second (FPS) velocity for the graphical visualization of the simulation execution. Each frame corresponds to one time step. Its range goes from 1 to 20 FPS, taking into account that, counterintuitively, 0 FPS set the fastest FPS velocity. One reason why the simulation might seem not be playing fluently could be the setting of the `FIRE_SPREAD_SPEED` variable referenced below.

### `Current step counter`

Indicates the current time step of the simulation.

# Common variables configuration

Global variables are used in the project to configure different simulation executions. In the next subsections several global variables descriptions are shown, as well as many configuration examples for execution.

## Variables description

### Forest area

`BATCH_SIZE`: It establishes how long the simulation will run, in number of time steps.

`WIDTH`, `HEIGHT`: They set the grid size (forest area size) in cells.

`BURNING_RATE`: It sets the fuel decay speed in terms of time steps.

`FIRE_SPREAD_SPEED`: it sets how fast fire spreads to other cells, in terms of time steps.

`FUEL_UPPER_LIMIT`, `FUEL_BOTTOM_LIMIT`: They establish the maximum and
minimum amount of burnable fuel present in each cell, respectively.

`DENSITY_PROB`: It is a value in the range `[0, 1]` that establishes the
percentage of the grid covered by vegetation.

### Ignition

Where and when the initial wildfire starts. Both can be fixed or randomised.

`FIRE_START_POSITION`: the cell the fire starts from.

| Value      | Meaning                                                                       |
|------------|-------------------------------------------------------------------------------|
| `None`     | the centre of the grid (the default)                                          |
| `"random"` | a uniformly random cell, never on the home base footprint                     |
| `(x, y)`   | that exact cell                                                                |

The ignition cell always holds a Fire agent, whatever `DENSITY_PROB` decides, so the fire has somewhere to start even on a sparse map.

`FIRE_START_STEP`: the simulation step the fire is lit at. Step 0 is the state the model is built in, so a fire lit at step 0 is already burning before the first step is taken.

| Value      | Meaning                                                            |
|------------|--------------------------------------------------------------------|
| `0`        | alight from the beginning of the run (the default)                 |
| an `int`   | exactly that step                                                  |
| `(a, b)`   | a random step drawn uniformly from the inclusive range `[a, b]`    |
| `"random"` | a random step anywhere in the run, `[0, BATCH_SIZE)`               |

Until that step nothing burns: the UAVs fly, MR2 accumulates, and MR1 stays at zero because there is nothing to monitor yet. The resolved cell and step are logged when the model is built, shown in the sidebar of the web interface, and recorded in the headless results as `fire_start_pos` and `fire_start_step`.

To try either from the command line, without editing `config.py`:

```bash
# a random cell, lit somewhere between steps 5 and 20
python3 headless.py --runs 5 --seed 1 --set FIRE_START_POSITION=random --set 'FIRE_START_STEP=(5, 20)'

# a specific corner, lit at step 10
python3 headless.py --set 'FIRE_START_POSITION=(3, 3)' --set FIRE_START_STEP=10
```

### Wind

`ACTIVATE_WIND`: It sets whether the fire spread is influenced by wind.

`FIXED_WIND`: If it is active, then wind blows in the direction set by `WIND_DIRECTION`. If it is not, it means wind blows two directions, specified by `FIRST_DIR` and `SECOND_DIR`. Since wind can blow a direction stronger than the other one, `FIRST_DIR_PROB` establishes the wind first direction’s predominance.

`PROBABILITY_MAP`: If it is active, the probability of the fire to spread to each cell at all times can be visualized.

`MU`: It sets how strong wind blows with a value in the range `[0, 1]`.

### Smoke

`ACTIVATE_SMOKE`: It sets whether smoke will be part of the simulation.

`SMOKE_PRE_DISPELLING_COUNTER`: It establishes how fast smoke appears after fire starts in a cell.

### UAV

`NUM_AGENTS`: It establishes the amount of UAVs that will fly over the forest area (zero indicates the simulator will simulate only the wildfire spread).

`N_ACTIONS`: Specifies the number of possible actions each UAV can take when deciding on a move, which by default is set as `[north, east, west, south]`.

`UAV_SPEED`: The maximum number of cells a UAV can cover in one time step. A policy returns a direction and a speed for each UAV (for example north at speed 3), and the UAV flies up to that many cells along that direction, stopping early at the edge of the grid, or on the cell of another UAV it has flown into. Set it to `1` for the original one cell per step behaviour, or to `0` to ground the fleet.

`UAV_OBSERVATION_RADIUS`: It sets the observation radius—technically it is not a radius, since observed areas have square shapes.

`SECURITY_DISTANCE`: The minimum separation, in cells, that the UAV team is meant to keep. It is a **scoring heuristic only**: `MR2` counts the pairs of UAVs that are closer than this to each other on each step, which measures how much collision risk a policy accepts. It does not stop a UAV from flying anywhere, and it is not what decides whether two UAVs have collided—see the health points below.

#### Health points and collisions

Two or more UAVs that end a time step **on the same cell** have collided. Each of them loses `UAV_COLLISION_DAMAGE` health points, and a UAV whose health points reach zero is destroyed: it is taken off the grid and out of the scheduler, stops observing, acting and scoring `MR1`, and takes no further part in the run. The rest of the team carries on, and the run itself continues even if the whole fleet is lost.

The **home base is shared airspace**: any number of UAVs can sit on its footprint without colliding, which is what lets the whole team start there and queue on it to refill. Flying over the base does not stop a UAV either. Everywhere else, a UAV that flies into an occupied cell takes that cell and its flight ends there, rather than passing over it.

Collisions are settled once per step, from where the UAVs ended up, so the damage does not depend on the order the scheduler happened to move them in, and two UAVs left stacked on one cell keep paying for it every step until they separate or are destroyed.

`UAV_HP`: Health points each UAV starts the run with. Set it high enough that collisions cost a policy something without ending its run outright, or to a very large number to study a fleet that cannot be destroyed.

`UAV_COLLISION_DAMAGE`: Health points lost per step spent sharing a cell with another UAV. With `UAV_HP = 1` and a damage of `1`, any collision destroys everybody involved in it.

The graphical interface reports the health of every UAV in the sidebar, with a bar that turns amber and then red as it drops, and marks a destroyed one as `DESTROYED`. The `Collisions` counter beside the metrics is how many times a cell was found holding more than one UAV; `headless.py` records the same as `collisions` and `uavs_lost` in its results.

### Firefighting extension

An optional extension that turns the simulation into a firefighting scenario. It is switched off by default; with `ACTIVATE_FIREFIGHTING = False` every variable in this section is ignored and the simulator behaves exactly as it did before the extension existed.

When it is switched on:

<ul>
  <li>a <b>home base</b> is placed on the map, drawn in blue, and every UAV starts from it;</li>
  <li>each UAV carries one <b>load of water</b>, and is drawn as a smaller dark blue square while it still has it;</li>
  <li>a UAV can <b>dump its water</b>, extinguishing the fire under it and around it;</li>
  <li>extinguished cells are drawn in light blue, are immune for a while, and can then <b>re-ignite</b>;</li>
  <li><b>out buildings</b> are scattered over the map, drawn in brown, and turn dark grey once they burn down;</li>
  <li>the run is <b>lost</b> if the home base burns for too long.</li>
</ul>

`ACTIVATE_FIREFIGHTING`: Master switch for the whole extension.

`BASE_POSITION`: Cell the home base is placed on, as an `(x, y)` tuple, or `None` to place it a quarter of the way into the grid. Note that the initial fire is lit at the centre of the grid, so putting the base there means it burns from the first step.

`BHP`: Base health points. The run is lost once the base cell has burned for this many steps. The damage is cumulative rather than consecutive, because a burning cell goes out for a step when none of its neighbours are alight yet, so the base collects its damage over several visits from the fire.

`BASE_REFILL_STEPS`: Steps a UAV has to spend on the base to take on a load of water. Refilling is not an action: a UAV with an empty tank standing on the base starts refilling by itself.

`BASE_CAPACITY`: How many UAVs can refill at the same time. The default of `1` means UAVs arriving together have to queue.

`UAV_WATER_CAPACITY`: Loads of water a UAV can carry at once.

`WATER_DROP_RADIUS`: How far a water drop reaches around the cell it is dumped on. The drop covers a disc, so the corners of the surrounding square are outside it.

`WATER_EXTINGUISH_PROB_CENTRE` and `WATER_EXTINGUISH_PROB_EDGE`: Probability of a drop extinguishing the cell right under it, and a cell at `WATER_DROP_RADIUS`. In between, the probability falls off linearly with the distance; beyond the radius it is zero.

`REIGNITION_DELAY`: Steps an extinguished cell is immune to catching fire again. Once the delay has passed, nearby fire can light it as usual.

`SPONTANEOUS_REIGNITION_PROB`: Per step probability that a cell which was extinguished at some point relights on its own, with no fire nearby. Keep it low.

`NUM_OUT_BUILDINGS`: Number of out buildings scattered randomly over the map. They are never placed on the home base, and if more are asked for than there are free cells, only what fits is placed.

`OUT_BUILDING_HP`: Steps an out building survives while its cell is burning, before it is destroyed.

The `firefighter` policy in `policy/firefighter.py` is written for this extension: it carries water to the fire, prefers fires that threaten an out building, dumps its load once in range, and flies back to the base to refill. It also keeps its team apart, sending no two UAVs to the same fire or through the same cell, so that it does not destroy its own fleet in collisions. The other policies still run with the extension switched on, but never dump water, since `ACTION_DUMP_WATER` sits outside `N_ACTIONS` and is only emitted by policies that opt in; `random` and `follow-fire` take no care to avoid each other either, so they lose UAVs to collisions.

To try it from the command line, without editing `config.py`:

```bash
python3 headless.py --policy firefighter --set ACTIVATE_FIREFIGHTING=True
```

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
