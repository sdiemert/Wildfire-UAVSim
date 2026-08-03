# =====================================================================================================
# # Wildfire-UAVSim configuration
#
# Every simulation setting lives in this file. Each entry below is written as
#
#     ### `NAME` -- what it does
#     **Bounds:** which values are legal
#
# and the sections follow the order a run is built up in: the environment first, then the forest, the
# ignition, the wind and the smoke, the UAVs, the optional firefighting extension, and finally the
# drawing colours. Nothing else belongs here: the shared maths that reads these settings lives in
# sim/formulas.py, which leaves this file as the settings alone.
#
# Any of these can also be overridden for a single run from the command line, without editing this file:
#
#     python3 headless.py --set DENSITY_PROB=0.6 --set 'FIRE_START_POSITION=(3, 3)'
#
# The bounds are stated but hardly ever enforced: a value outside them usually still runs, and quietly
# gives nonsense. The few that raise are called out individually.
# =====================================================================================================

import random

# =====================================================================================================
# ## Random number source
# =====================================================================================================

# ### `SYSTEM_RANDOM` -- the generator every stochastic decision in the simulator draws from.
# Replacing it with a seeded generator, as `headless.py --seed` and the test fixtures do, makes a run
# reproducible.
# **Bounds:** a `random.Random` instance. `random.SystemRandom()` is not available on all systems.
SYSTEM_RANDOM = random.SystemRandom()

# =====================================================================================================
# ## Environment switches
#
# What the simulated world contains. Read all over the project, so best left alone once a run has begun.
# =====================================================================================================

# ### `ACTIVATE_WIND` -- whether wind skews the direction the fire spreads in.
# With it off, `MU`, `WIND_DIRECTION` and the composed wind settings are ignored.
# **Bounds:** `True` / `False`.
ACTIVATE_WIND = True

# ### `FIXED_WIND` -- whether the wind blows from one direction or two.
# `True` uses `WIND_DIRECTION` alone; `False` composes `FIRST_DIR` and `SECOND_DIR`.
# **Bounds:** `True` / `False`.
FIXED_WIND = False

# ### `ACTIVATE_SMOKE` -- whether burning cells raise smoke, hiding what is underneath.
# **Bounds:** `True` / `False`.
ACTIVATE_SMOKE = True

# ### `PROBABILITY_MAP` -- draw each cell's probability of catching fire instead of the forest.
# **Bounds:** `True` / `False`. Requires `NUM_AGENTS = 0`: nothing but the fire is drawn on the
# probability map, so a UAV would get a portrayal with no "Layer" attribute out of `portrayal_method(obj)`
# and the canvas would throw `KeyError: 'Layer'`.
PROBABILITY_MAP = False

# =====================================================================================================
# ## Forest area
#
# How large the map is, and how much there is to burn on it.
# =====================================================================================================

# ### `BATCH_SIZE` -- how long a run lasts, in simulation steps.
# The web interface shows `Done` once it is reached; `headless.py --steps` overrides it.
# **Bounds:** integer `>= 1`.
BATCH_SIZE = 100

# ### `WIDTH`, `HEIGHT` -- grid size (forest area size), in cells.
# The web canvas is drawn at 10 pixels per cell, so a grid much past ~100 stops fitting on screen.
# **Bounds:** integers `>= 1`. Run time grows with `WIDTH * HEIGHT`.
WIDTH = 50  # in python [height, width] for grid, in js [width, heigh]
HEIGHT = 50

# ### `FUEL_UPPER_LIMIT`, `FUEL_BOTTOM_LIMIT` -- burnable fuel each cell starts with.
# Every cell draws uniformly from the inclusive range, and burns for that many fire updates.
# **Bounds:** integers, `1 <= FUEL_BOTTOM_LIMIT <= FUEL_UPPER_LIMIT`. `FUEL_UPPER_LIMIT` also scales the
# vegetation and fire colour ramps, so it must stay `> 0`.
FUEL_UPPER_LIMIT = 10
FUEL_BOTTOM_LIMIT = 5

# ### `BURNING_RATE` -- fuel a burning cell loses per fire update.
# Larger means cells burn out sooner, so the fire front is thinner and moves on faster.
# **Bounds:** integer `>= 1`. Anything past `FUEL_UPPER_LIMIT` burns every cell out in a single update.
BURNING_RATE = 1

# ### `FIRE_SPREAD_SPEED` -- simulation steps between fire updates, so larger means slower spread.
# Everything else (UAVs, water drops, the immunity countdown) still runs every step.
# **Bounds:** integer `>= 1`, where `1` is the fastest spread available. `0` raises `ZeroDivisionError`,
# and a fraction never satisfies the integer modulo in `Fire.step()`, which freezes the fire entirely.
FIRE_SPREAD_SPEED = 2

# ### `DENSITY_PROB` -- share of the grid covered by vegetation (tree density).
# Each cell independently gets a Fire agent with this probability; a cell without one never burns.
# **Bounds:** float in `[0, 1]`. `1` is a fully wooded map, `0` an empty one bar the ignition cell.
DENSITY_PROB = 0.9

# =====================================================================================================
# ## Ignition
#
# Where and when the initial wildfire starts; either can be fixed or randomised. The cell and step that
# get resolved are logged when the model is built, shown in the sidebar of the web interface, and
# recorded by `headless.py` as `fire_start_pos` and `fire_start_step`.
# =====================================================================================================

# ### `FIRE_START_POSITION` -- the cell the fire starts from.
# The ignition cell always holds a Fire agent whatever `DENSITY_PROB` decides, so the fire has somewhere
# to start even on a sparse map.
# **Bounds:** one of
#   None      -> the centre of the grid
#   "random"  -> a uniformly random cell, avoiding the home base footprint
#   (x, y)    -> that exact cell, which must lie inside the grid
FIRE_START_POSITION = "random"

# ### `FIRE_START_STEP` -- the simulation step the fire is lit at.
# Step 0 is the state the model is built in, so a fire lit at step 0 is already burning before the first
# step is taken. Until that step nothing burns: the UAVs fly, MR2 accumulates, and MR1 stays at zero.
# **Bounds:** one of
#   an int    -> exactly that step, >= 0. A value >= BATCH_SIZE is warned about and never lights
#   (a, b)    -> a random step drawn uniformly from the inclusive range [a, b], with 0 <= a <= b
#   "random"  -> a random step anywhere in the run, [0, BATCH_SIZE)
FIRE_START_STEP = (10, 20)

# =====================================================================================================
# ## Wind
#
# Ignored unless `ACTIVATE_WIND` is True. Wind raises the chance of spreading downwind and lowers it
# upwind, by a fraction `MU` of the probability that is left.
# =====================================================================================================

# ### `WIND_DIRECTION` -- the single direction the wind blows, used when `FIXED_WIND` is True.
# **Bounds:** one of 'north', 'south', 'east', 'west'. Anything else raises `ValueError` in
# `fire_spread.build_kernel()`.
WIND_DIRECTION = 'south'

# Composed wind. Read only when `FIXED_WIND` is False, but defined either way: a name that exists under
# one setting and not the other cannot be overridden from the command line (`headless.py --set` rejects it
# as an unknown constant) and turns any stray read into a NameError instead of a wrong answer. Mixing two
# perpendicular directions gives a diagonal wind: NW, NE, SW or SE.

# ### `FIRST_DIR` -- the predominant wind direction.
# **Bounds:** one of 'north', 'south', 'east', 'west'.
FIRST_DIR = 'south'

# ### `SECOND_DIR` -- the other direction, blown whenever the first one is not.
# **Bounds:** one of 'north', 'south', 'east', 'west'.
SECOND_DIR = 'east'

# ### `FIRST_DIR_PROB` -- how far `FIRST_DIR` predominates, drawn afresh per cell per update.
# **Bounds:** float in `[0, 1]`. `1` collapses onto `FIRST_DIR`, `0` onto `SECOND_DIR`, and `0.5`
# splits the wind evenly between the two.
FIRST_DIR_PROB = 0.8

# ### `MU` -- wind strength (wind velocity).
# The fraction of the remaining probability that blowing downwind adds, and blowing upwind takes away.
# **Bounds:** float in `[0, 1]`. `0` makes the wind irrelevant, `1` makes it absolute.
MU = 0.5

# =====================================================================================================
# ## Smoke
#
# Ignored unless `ACTIVATE_SMOKE` is True. A cell raises smoke a while after it catches fire, and that
# smoke then hangs about for as many steps as the cell had fuel.
# =====================================================================================================

# ### `SMOKE_PRE_DISPELLING_COUNTER` -- steps between a cell catching fire and its smoke appearing.
# The smoke then lasts for the cell's initial fuel, set as `self.dispelling_counter_start_value` in
# `Smoke.__init__()` in `sim/environment.py`. Keep the sum of the two above `FUEL_UPPER_LIMIT`, or the smoke
# clears before the cell has finished burning.
# **Bounds:** integer `>= 0`, where `0` raises smoke the moment the cell ignites.
SMOKE_PRE_DISPELLING_COUNTER = 2

# =====================================================================================================
# ## UAVs
#
# The team that flies over the forest area. `NUM_AGENTS = 0` simulates the wildfire on its own.
# =====================================================================================================

# ### `NUM_AGENTS` -- how many UAVs fly over the forest area.
# **Bounds:** integer `>= 0`, and no larger than `WIDTH * HEIGHT`, since the team launches unstacked.
# Must be `0` when `PROBABILITY_MAP` is True.
NUM_AGENTS = 4

# ### `N_ACTIONS` -- size of the movement action space a policy draws from.
# The four movement directions below are indices 0..3. Holding position and dumping water sit outside
# the space on purpose, so that the random baseline keeps drawing from the original four.
# **Bounds:** `4` (the default), or `5` to bring `ACTION_STAY` into the action space of a learning
# algorithm. `ACTION_DUMP_WATER` is only ever emitted by policies that opt into it.
N_ACTIONS = 4

# ### Action indices -- fixed constants, not tuning parameters. Do not renumber.
# They index the movement vectors in `UAV.move()`, and are what a policy returns from `select_actions()`.
ACTION_RIGHT = 0
ACTION_DOWN = 1
ACTION_LEFT = 2
ACTION_UP = 3
ACTION_STAY = 4         # hold position; deliberately outside N_ACTIONS
ACTION_DUMP_WATER = 5   # firefighting extension only; likewise outside N_ACTIONS

# ### `MOVEMENT_VECTORS` -- how far one cell of movement takes a UAV, per direction.
# `UAV.move()` flies along these, and a policy that has to work out where an action would land it reads
# the same table, so the two cannot drift apart. Fixed constants, not tuning parameters.
MOVEMENT_VECTORS = {
    ACTION_RIGHT: (1, 0),
    ACTION_DOWN: (0, -1),
    ACTION_LEFT: (-1, 0),
    ACTION_UP: (0, 1),
}

# ### `UAV_SPEED` -- the most cells a UAV can cover in one time step.
# A policy asks for a direction and a speed, and the UAV covers up to this many cells along that
# direction, stopping early at the edge of the grid or in front of another UAV.
# **Bounds:** integer `>= 0`. `1` gives the original one cell per step behaviour, `0` grounds the fleet.
UAV_SPEED = 5

# ### `UAV_OBSERVATION_RADIUS` -- how far a UAV sees, in cells.
# Not really a radius: the observed area is the square of side `2 * radius + 1` centred on the UAV.
# **Bounds:** integer `>= 0`. A radius below `UAV_SPEED` lets a UAV fly past what it can see, and so into
# teammates it was never told were there.
UAV_OBSERVATION_RADIUS = 4

# derived from the radius above; headless.py recomputes both when it overrides it
side = ((UAV_OBSERVATION_RADIUS * 2) + 1)
N_OBSERVATIONS = side * side

# ### `SECURITY_DISTANCE` -- the separation, in cells, that the UAV team is meant to keep.
# A **scoring heuristic only**: MR2 counts the pairs of UAVs that end a step closer than this to each
# other, which is a proxy for how much collision risk a policy accepts. It does not stop a UAV from
# flying anywhere, and it is not what decides whether two UAVs collided -- that is a matter of sharing a
# cell, see `UAV_HP` below.
# **Bounds:** number `>= 0`. `0` never scores; more than the grid diagonal scores every pair every step.
SECURITY_DISTANCE = 2

# ### `UAV_HP` -- health points each UAV starts the run with.
# Two or more UAVs that end a step on the same cell have collided, and each of them rolls for damage; a
# UAV whose health points reach zero is destroyed and takes no further part in the run. The home base is
# the one exception: any number of UAVs can sit on its footprint without colliding, which is what lets
# the whole team start and refill there.
# **Bounds:** integer `>= 1`. Set it high enough that collisions cost a policy something without ending
# its run outright, or to a very large number to study a fleet that cannot be destroyed.
UAV_HP = 3

# ### `UAV_COLLISION_DAMAGE_MEAN` -- average health points a collision costs one UAV.
# The damage is rolled once per UAV per collision and is either a whole health point or nothing at all,
# so health points stay whole numbers while the expected cost of a collision is this value:
#   1.0  -> a full health point every time, which is the default
#   0.25 -> one health point in four collisions on average, and three that do no harm
#   0.0  -> collisions are still counted and logged, but never damage anybody
# **Bounds:** float in `[0, 1]`. Anything outside it is clamped by `formulas.roll_collision_damage()`,
# because a collision can never cost more than one health point.
UAV_COLLISION_DAMAGE_MEAN = 1.0

# =====================================================================================================
# ## Fuel extension
#
# Optional. When `ACTIVATE_FUEL` is False no fuel is burned, tracked or reported, and the simulation
# behaves exactly as it did before the extension existed. When it is True every UAV burns fuel to stay
# in the air, and one that runs dry loses every health point it has left and is destroyed, exactly as a
# fatal collision destroys it.
#
# Note that "fuel" means two unrelated things in this project. The `FUEL_UPPER_LIMIT` and
# `FUEL_BOTTOM_LIMIT` in the forest area section above are how much a vegetation cell has left to burn.
# Everything in this section is the fuel in a UAV's tank, and the two never interact.
#
# Refuelling happens at the home base, so it needs `ACTIVATE_FIREFIGHTING` to be True as well. With fuel
# on and the firefighting extension off there is nowhere to refuel, which turns `UAV_FUEL` into a hard
# endurance limit on the whole run.
# =====================================================================================================

# ### `ACTIVATE_FUEL` -- master switch for the whole extension.
# **Bounds:** `True` / `False`.
ACTIVATE_FUEL = True

# ### `UAV_FUEL` -- units of fuel in a full tank, which is what every UAV starts the run with.
# What this buys depends on how the UAV is flown: at the defaults below, holding position costs 1 a step
# and cruising three cells a step costs about 6.2, so a 150 unit tank is either 150 steps of loitering or
# about 24 steps of cruising. Size it against `BATCH_SIZE` and the number of sorties a run should allow.
# **Bounds:** number `> 0`. A very large value studies a fleet that never runs dry.
#
# Note that a tank only lasts a run if the policy flying it ever goes home to refuel. `firefighter` does,
# because it reads `Observation.low_fuel()`, and comes back with fuel to spare; `random` and `follow-fire`
# do not, so they drain any tank and lose the whole fleet part way through the run, whatever this is set
# to. That is a property of those baselines rather than of the size of the tank.
UAV_FUEL = 150

# ### `UAV_FUEL_IDLE_BURN` -- fuel burned per step spent airborne, whatever the UAV did.
# Charged for holding position and for dumping water as well as for flying, so staying up costs
# something. A UAV parked on the home base footprint burns nothing at all: engines off.
# **Bounds:** number `>= 0`. `0` lets a UAV loiter for free, so only distance costs.
UAV_FUEL_IDLE_BURN = 1.0

# ### `UAV_FUEL_BURN_PER_CELL` -- fuel burned per cell of flight, before the speed penalty below.
# Charged on the cells actually covered, so a UAV stopped early by the edge of the grid or by another UAV
# only pays for the distance it really flew.
# **Bounds:** number `>= 0`. `0` makes movement free, leaving the idle burn as a pure clock.
UAV_FUEL_BURN_PER_CELL = 1.0

# ### `UAV_FUEL_SPEED_EXPONENT` -- how much harder each extra cell of speed is on the tank.
# The per cell cost is raised to this power, so above `1` covering ground quickly costs more than covering
# the same ground slowly, the way the power a real airframe draws climbs steeply with airspeed:
#   1.0 -> flat. Five cells cost five times one cell, whether flown in one step or five
#   1.5 -> the default. Five cells in one step cost 11.2, against 5.0 flown one cell at a time
#   2.0 -> harsh. Five cells in one step cost 25.0, so sprinting is a serious decision
# **Bounds:** number `>= 0`. Below `1` it rewards sprinting instead, which is not physical but is a
# legitimate thing to experiment with.
UAV_FUEL_SPEED_EXPONENT = 1.5

# ### `UAV_FUEL_RESERVE` -- the share of a tank at or below which a policy should turn for home.
# Advisory only: nothing in the simulation enforces it. `Observation.low_fuel()` reports it, and the
# `firefighter` policy breaks off whatever it is doing and flies back to the base once it is reached.
# **Bounds:** float in `[0, 1]`. `0` never warns, so a policy reading it flies until the tank is empty;
# `1` sends a UAV home the moment it is anything short of full.
UAV_FUEL_RESERVE = 0.25

# ### `BASE_REFUEL_STEPS` -- steps a UAV must spend at the base to fill its tank.
# Refuelling is not an action, and shares the refilling slot with water: a UAV standing on the base that
# wants either takes one of the `BASE_CAPACITY` slots, waits `max(BASE_REFILL_STEPS, BASE_REFUEL_STEPS)`
# steps, and gets both at once. Ignored unless `ACTIVATE_FUEL` is True.
# **Bounds:** integer `>= 1`. `0` behaves the same as `1`, as a refuel still takes the step it starts on.
BASE_REFUEL_STEPS = 2

# =====================================================================================================
# ## Firefighting extension
#
# Optional. When `ACTIVATE_FIREFIGHTING` is False every variable in this section is ignored and the
# simulation behaves exactly as it did before the extension existed. When it is True the simulation
# gains a home base, water carrying UAVs, extinguishing, re-ignition and out buildings.
# =====================================================================================================

# ### `ACTIVATE_FIREFIGHTING` -- master switch for the whole extension.
# **Bounds:** `True` / `False`.
ACTIVATE_FIREFIGHTING = True

# ### `BASE_POSITION` -- the cell the home base is anchored on, its bottom left corner.
# UAVs start here and come back to refill. The default deliberately avoids the centre, because that is
# where `set_fire_agents()` lights the initial fire by default: a base on top of the ignition cell would
# be alight from step 1 and the UAVs would put the wildfire out before it ever spread.
# **Bounds:** an `(x, y)` cell inside the grid, or `None` to place the base a quarter of the way in. A
# position outside the grid raises `ValueError`.
BASE_POSITION = None

# ### `BASE_SIZE` -- footprint of the base, in cells, as `(width, height)`.
# The whole footprint is drawn blue, burns, and can be refilled from. The team is spread over it at the
# start of a run, one UAV per cell in order, so the fleet is visible from the first step and does not
# launch on top of itself; a team that outnumbers the footprint spills into the rings around the base.
# **Bounds:** a pair of integers `>= 1`, clipped to the grid at the edges.
BASE_SIZE = (2, 2)

# ### `BHP` -- base health points: the run is lost once the base has burned for this many steps.
# The damage is cumulative rather than consecutive, because a burning cell goes out for a step when none
# of its neighbours are alight yet, so the base collects its damage over several visits from the fire.
# **Bounds:** integer `>= 1`.
BHP = 5

# ### `BASE_REFILL_STEPS` -- steps a UAV must spend at the base to take on a load of water.
# Refilling is not an action: a UAV with an empty tank standing on the base starts refilling by itself.
# **Bounds:** integer `>= 1`. `0` behaves the same as `1`, as a refill still takes the step it starts on.
BASE_REFILL_STEPS = 1

# ### `BASE_CAPACITY` -- how many UAVs can refill at the same time.
# **Bounds:** integer `>= 1`. The default of `1` (which is the requirement) makes arrivals queue.
BASE_CAPACITY = 1

# ### `UAV_WATER_CAPACITY` -- loads of water a UAV can carry at once.
# **Bounds:** integer `>= 1`.
UAV_WATER_CAPACITY = 1

# ### `WATER_DROP_RADIUS` -- how far a water drop reaches around the cell it is dumped on, in cells.
# The drop covers a disc, so the corners of the surrounding square fall outside it.
# **Bounds:** integer `>= 0`, where `0` wets only the target cell.
WATER_DROP_RADIUS = 2

# ### `WATER_EXTINGUISH_PROB_CENTRE`, `WATER_EXTINGUISH_PROB_EDGE` -- how well a drop puts a fire out.
# The chance of extinguishing the cell the water is dumped on, and one at `WATER_DROP_RADIUS`. In between
# the probability falls off linearly with the distance; beyond the radius it is zero.
# **Bounds:** floats in `[0, 1]`, normally with centre `>=` edge. The reverse is allowed, and simply
# makes the drop stronger at its rim than under itself.
WATER_EXTINGUISH_PROB_CENTRE = 0.95
WATER_EXTINGUISH_PROB_EDGE = 0.60

# ### `REIGNITION_DELAY` -- steps an extinguished cell is immune to catching fire again.
# Once the delay has passed, nearby fire can light the cell as usual.
# **Bounds:** integer `>= 0`, where `0` lets a cell relight the step after it was doused.
REIGNITION_DELAY = 8

# ### `SPONTANEOUS_REIGNITION_PROB` -- per step chance an extinguished cell relights on its own.
# Applies with no fire nearby, to any cell that was extinguished at some point and still has fuel.
# **Bounds:** float in `[0, 1]`. Keep it low: it is rolled for every such cell on every step.
SPONTANEOUS_REIGNITION_PROB = 0.005

# ### `NUM_OUT_BUILDINGS` -- out buildings scattered over the map, which burn and are worth protecting.
# Never placed on the home base. If more are asked for than there are free cells, only what fits is placed.
# **Bounds:** integer `>= 0`.
NUM_OUT_BUILDINGS = 0

# ### `OUT_BUILDING_HP` -- steps an out building survives while its cell burns, before it is destroyed.
# **Bounds:** integer `>= 1`.
OUT_BUILDING_HP = 5

# =====================================================================================================
# ## Colours
#
# Presentation only: these change what the web interface draws, never what the simulation does.
# **Bounds:** CSS colour strings, "#rrggbb".
#
# The map is kept light on purpose. Everything that has to be found at a glance -- the UAVs, the home base,
# the out buildings -- is drawn dark and small over a background of vegetation that covers most of the
# grid, so the darker that background is the harder those things are to pick out. The vegetation therefore
# runs from near white to a mid green rather than down into the near blacks it used to reach, and the fire
# runs from pale yellow to a bright red orange, which keeps it the most saturated thing on the map without
# it going dark either.

BASE_COLOR = "#1d4ed8"  # blue, as the home base is shown on the map
BASE_BURNING_COLOR = "#6d28d9"
# UAVs are always drawn in the same near black, which is what keeps them findable over the light map. The
# water a UAV carries is shown by how big it is drawn rather than by another colour: colouring the load in
# would mean drawing a loaded UAV in something lighter, which is what made it hard to find in the first
# place. See agent_portrayal() in main.py.
UAV_COLOR = "#111827"  # near black, the darkest thing on the map
# hairline drawn around a UAV, so that it keeps an edge over the base and over burnt ground, which are the
# only two things on the map anywhere near as dark as it is
UAV_OUTLINE_COLOR = "#f8fafc"
# the square marking what a UAV can see, drawn in sim/gui/canvas_grid.py. It is deliberately lighter
# than UAV_COLOR: with a team of any size these squares cover much of the map, and drawn as dark as the
# UAVs themselves they hide the very things they are meant to be drawn around.
UAV_OBSERVATION_COLOR = "#64748b"
OUT_BUILDING_COLOR = "#7c4a21"
OUT_BUILDING_DESTROYED_COLOR = "#3b3b3b"
EXTINGUISHED_COLOR = "#1f9fc7"  # cells that were recently hit by water

# index 0 of both ramps is a burnt out cell, which is why the two share it. It is a mid grey rather than
# the near black it was, so that a UAV flying over ground the fire has already been through is still
# visible, and warm enough not to be taken for smoke.
BURNT_COLOR = "#8a8078"

# ramps indexed by the fuel a cell has left, burnt out first. VEGETATION_COLORS and FIRE_COLORS must be
# the same length, which COLORS_LEN takes from the first of them.
VEGETATION_COLORS = [BURNT_COLOR, "#f1f9e8", "#e4f4d8", "#d8eec9", "#cce9ba", "#bfe4aa",
                     "#b3df9b", "#a6d98b", "#9ad47c", "#8dcf6c", "#81c95d", "#74c44d"]
FIRE_COLORS = [BURNT_COLOR, "#ffeeaa", "#ffdc8c", "#ffcb6e", "#ffb950", "#ffa832",
               "#ff9614", "#fb8414", "#f67113", "#f25f13", "#ed4c12", "#e93a12"]
# a neutral grey, dark enough to read against the vegetation and light enough not to be taken for
# burnt ground. Smoke is meant to hide what is under it, so it does not fight for attention.
SMOKE_COLORS = ["#a8b0bd"]  # only the first entry is used
# ramp for PROBABILITY_MAP, indexed by the probability rounded to one decimal, so it needs 11 entries
BLACK_AND_WHITE_COLORS = ["#ffffff", "#e6e6e6", "#c9c9c9", "#b1b1b1", "#a1a1a1", "#818181",
                          "#636363", "#474747", "#303030", "#1a1a1a", "#000000"]
COLORS_LEN = len(VEGETATION_COLORS)


# =====================================================================================================
# ## Validation
#
# The bounds stated against each setting above are checked here, once, at the start of a run. Without
# this an out of bounds value either runs and quietly gives nonsense, or fails much later and far from
# its cause: FIRE_SPREAD_SPEED = 0 raises ZeroDivisionError inside Fire.step(), a FUEL_BOTTOM_LIMIT above
# FUEL_UPPER_LIMIT raises ValueError once per cell out of randint(), and PROBABILITY_MAP with a UAV on
# the map throws KeyError: 'Layer' from the canvas.
#
# Only the settings whose bounds actually matter are checked; the colours and the advisory thresholds are
# left alone. WildFireModel.__init__() calls this, so it covers the web interface and the headless runner
# alike, and headless.py calls it again after applying --set overrides.
# =====================================================================================================

# every direction the wind logic understands, in agents.Wind and in fire_spread.build_kernel()
WIND_DIRECTIONS = ('north', 'south', 'east', 'west')


# checks the configuration over, raising ValueError describing everything that is wrong with it rather
# than only the first thing found, so that a badly set up run is fixed in one pass
def validate():
    problems = []

    def require(condition, message):
        if not condition:
            problems.append(message)

    # forest area
    require(isinstance(BATCH_SIZE, int) and BATCH_SIZE >= 1,
            f"BATCH_SIZE must be an integer >= 1, got {BATCH_SIZE!r}")
    require(isinstance(WIDTH, int) and WIDTH >= 1, f"WIDTH must be an integer >= 1, got {WIDTH!r}")
    require(isinstance(HEIGHT, int) and HEIGHT >= 1, f"HEIGHT must be an integer >= 1, got {HEIGHT!r}")
    require(1 <= FUEL_BOTTOM_LIMIT <= FUEL_UPPER_LIMIT,
            f"FUEL_BOTTOM_LIMIT {FUEL_BOTTOM_LIMIT} and FUEL_UPPER_LIMIT {FUEL_UPPER_LIMIT} must "
            "satisfy 1 <= bottom <= upper")
    require(isinstance(BURNING_RATE, int) and BURNING_RATE >= 1,
            f"BURNING_RATE must be an integer >= 1, got {BURNING_RATE!r}")
    # a non integer never satisfies the modulo in Fire.step() and freezes the fire; zero divides by it
    require(isinstance(FIRE_SPREAD_SPEED, int) and FIRE_SPREAD_SPEED >= 1,
            f"FIRE_SPREAD_SPEED must be an integer >= 1, got {FIRE_SPREAD_SPEED!r}")
    require(0.0 <= DENSITY_PROB <= 1.0, f"DENSITY_PROB must be in [0, 1], got {DENSITY_PROB!r}")

    # wind. The composed directions are only read when the wind is on and not fixed, but they are always
    # defined, so they are always worth checking
    if ACTIVATE_WIND:
        require(0.0 <= MU <= 1.0, f"MU must be in [0, 1], got {MU!r}")
        if FIXED_WIND:
            require(WIND_DIRECTION in WIND_DIRECTIONS,
                    f"WIND_DIRECTION must be one of {WIND_DIRECTIONS}, got {WIND_DIRECTION!r}")
        else:
            require(FIRST_DIR in WIND_DIRECTIONS,
                    f"FIRST_DIR must be one of {WIND_DIRECTIONS}, got {FIRST_DIR!r}")
            require(SECOND_DIR in WIND_DIRECTIONS,
                    f"SECOND_DIR must be one of {WIND_DIRECTIONS}, got {SECOND_DIR!r}")
            require(0.0 <= FIRST_DIR_PROB <= 1.0,
                    f"FIRST_DIR_PROB must be in [0, 1], got {FIRST_DIR_PROB!r}")

    # smoke
    require(isinstance(SMOKE_PRE_DISPELLING_COUNTER, int) and SMOKE_PRE_DISPELLING_COUNTER >= 0,
            f"SMOKE_PRE_DISPELLING_COUNTER must be an integer >= 0, got {SMOKE_PRE_DISPELLING_COUNTER!r}")

    # UAVs
    require(isinstance(NUM_AGENTS, int) and NUM_AGENTS >= 0,
            f"NUM_AGENTS must be an integer >= 0, got {NUM_AGENTS!r}")
    if isinstance(NUM_AGENTS, int) and isinstance(WIDTH, int) and isinstance(HEIGHT, int):
        # same wording as the check in WildFireModel.launch_positions(), which is the other place this
        # can be discovered: one problem, one message
        require(NUM_AGENTS <= WIDTH * HEIGHT,
                f"{NUM_AGENTS} UAVs do not fit on the {HEIGHT}x{WIDTH} grid: "
                "lower NUM_AGENTS or enlarge the grid")
    require(N_ACTIONS in (4, 5), f"N_ACTIONS must be 4 or 5, got {N_ACTIONS!r}")
    require(isinstance(UAV_SPEED, int) and UAV_SPEED >= 0,
            f"UAV_SPEED must be an integer >= 0, got {UAV_SPEED!r}")
    require(isinstance(UAV_OBSERVATION_RADIUS, int) and UAV_OBSERVATION_RADIUS >= 0,
            f"UAV_OBSERVATION_RADIUS must be an integer >= 0, got {UAV_OBSERVATION_RADIUS!r}")
    require(SECURITY_DISTANCE >= 0, f"SECURITY_DISTANCE must be >= 0, got {SECURITY_DISTANCE!r}")
    require(isinstance(UAV_HP, int) and UAV_HP >= 1, f"UAV_HP must be an integer >= 1, got {UAV_HP!r}")

    # nothing but the fire is drawn on the probability map, so a UAV would get a portrayal with no
    # "Layer" attribute and the canvas would throw KeyError: 'Layer'
    require(not (PROBABILITY_MAP and NUM_AGENTS), "PROBABILITY_MAP requires NUM_AGENTS = 0")

    # fuel extension
    if ACTIVATE_FUEL:
        require(UAV_FUEL > 0, f"UAV_FUEL must be > 0, got {UAV_FUEL!r}")
        require(UAV_FUEL_IDLE_BURN >= 0,
                f"UAV_FUEL_IDLE_BURN must be >= 0, got {UAV_FUEL_IDLE_BURN!r}")
        require(UAV_FUEL_BURN_PER_CELL >= 0,
                f"UAV_FUEL_BURN_PER_CELL must be >= 0, got {UAV_FUEL_BURN_PER_CELL!r}")
        require(UAV_FUEL_SPEED_EXPONENT >= 0,
                f"UAV_FUEL_SPEED_EXPONENT must be >= 0, got {UAV_FUEL_SPEED_EXPONENT!r}")
        require(0.0 <= UAV_FUEL_RESERVE <= 1.0,
                f"UAV_FUEL_RESERVE must be in [0, 1], got {UAV_FUEL_RESERVE!r}")
        require(isinstance(BASE_REFUEL_STEPS, int) and BASE_REFUEL_STEPS >= 0,
                f"BASE_REFUEL_STEPS must be an integer >= 0, got {BASE_REFUEL_STEPS!r}")

    # firefighting extension
    if ACTIVATE_FIREFIGHTING:
        require(len(BASE_SIZE) == 2 and all(isinstance(side_, int) and side_ >= 1 for side_ in BASE_SIZE),
                f"BASE_SIZE must be a pair of integers >= 1, got {BASE_SIZE!r}")
        require(isinstance(BHP, int) and BHP >= 1, f"BHP must be an integer >= 1, got {BHP!r}")
        require(isinstance(BASE_REFILL_STEPS, int) and BASE_REFILL_STEPS >= 0,
                f"BASE_REFILL_STEPS must be an integer >= 0, got {BASE_REFILL_STEPS!r}")
        require(isinstance(BASE_CAPACITY, int) and BASE_CAPACITY >= 1,
                f"BASE_CAPACITY must be an integer >= 1, got {BASE_CAPACITY!r}")
        require(isinstance(UAV_WATER_CAPACITY, int) and UAV_WATER_CAPACITY >= 1,
                f"UAV_WATER_CAPACITY must be an integer >= 1, got {UAV_WATER_CAPACITY!r}")
        require(isinstance(WATER_DROP_RADIUS, int) and WATER_DROP_RADIUS >= 0,
                f"WATER_DROP_RADIUS must be an integer >= 0, got {WATER_DROP_RADIUS!r}")
        require(0.0 <= WATER_EXTINGUISH_PROB_CENTRE <= 1.0,
                f"WATER_EXTINGUISH_PROB_CENTRE must be in [0, 1], got {WATER_EXTINGUISH_PROB_CENTRE!r}")
        require(0.0 <= WATER_EXTINGUISH_PROB_EDGE <= 1.0,
                f"WATER_EXTINGUISH_PROB_EDGE must be in [0, 1], got {WATER_EXTINGUISH_PROB_EDGE!r}")
        require(isinstance(REIGNITION_DELAY, int) and REIGNITION_DELAY >= 0,
                f"REIGNITION_DELAY must be an integer >= 0, got {REIGNITION_DELAY!r}")
        require(0.0 <= SPONTANEOUS_REIGNITION_PROB <= 1.0,
                f"SPONTANEOUS_REIGNITION_PROB must be in [0, 1], got {SPONTANEOUS_REIGNITION_PROB!r}")
        require(isinstance(NUM_OUT_BUILDINGS, int) and NUM_OUT_BUILDINGS >= 0,
                f"NUM_OUT_BUILDINGS must be an integer >= 0, got {NUM_OUT_BUILDINGS!r}")
        require(isinstance(OUT_BUILDING_HP, int) and OUT_BUILDING_HP >= 1,
                f"OUT_BUILDING_HP must be an integer >= 1, got {OUT_BUILDING_HP!r}")
    # ACTIVATE_FUEL without ACTIVATE_FIREFIGHTING is deliberately not an error: there is simply nowhere to
    # refuel, which turns UAV_FUEL into a hard endurance limit on the whole run. See the note against
    # ACTIVATE_FUEL above.

    if problems:
        raise ValueError("invalid configuration:\n  - " + "\n  - ".join(problems))
