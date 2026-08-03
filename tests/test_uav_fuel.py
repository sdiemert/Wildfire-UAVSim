"""Tests for the UAV fuel extension: burning it, running out of it, and refuelling at the base.

A UAV burns fuel to stay in the air, and one that runs dry loses every health point it has left and is
destroyed, exactly as a fatal collision destroys it. The cost of a step is

    idle + UAV_FUEL_BURN_PER_CELL * cells ** UAV_FUEL_SPEED_EXPONENT

where the idle burn is charged for staying up at all and waived for a UAV parked on the home base. With
the exponent above 1, covering ground in one fast dash costs more than covering it slowly.

The whole thing is behind ACTIVATE_FUEL, which is off by default, so the first section here pins that a
run without it behaves exactly as it did before the extension existed.

Direction reminder, from the movement vectors in UAV.move():
    ACTION_RIGHT  x + 1        ACTION_LEFT  x - 1
    ACTION_UP     y + 1        ACTION_DOWN  y - 1
"""

# python libraries

import pytest

# own python modules

import config

from config import ACTION_RIGHT, ACTION_STAY

from policy import Action, FirefighterPolicy, Policy


# --- helpers ----------------------------------------------------------------


class ScriptedPolicy(Policy):
    """Gives the UAVs the actions listed by their place in the team, holding position for the rest."""

    name = "scripted"

    def __init__(self, actions=None):
        self.actions = dict(actions or {})

    def select_actions(self, observations):
        return [self.actions.get(index, Action(ACTION_STAY, 0))
                for index, _ in enumerate(observations)]


@pytest.fixture
def fleet(make_model):
    """A model flying UAVs on a 9x9 grid with the fuel extension on and the fire kept out of the way.

    The burn is pinned to the documented defaults rather than to whatever config.py happens to be set to,
    so the arithmetic in these tests is fixed. The firefighting extension is off unless a test asks for it,
    which is also what leaves the UAVs nowhere to refuel.
    """

    def _make(count=1, **overrides):
        settings = {"NUM_AGENTS": count, "ACTIVATE_FIREFIGHTING": False,
                    "FIRE_START_STEP": 10_000, "UAV_SPEED": 5,
                    "ACTIVATE_FUEL": True, "UAV_FUEL": 100.0,
                    "UAV_FUEL_IDLE_BURN": 1.0, "UAV_FUEL_BURN_PER_CELL": 1.0,
                    "UAV_FUEL_SPEED_EXPONENT": 1.5, "UAV_FUEL_RESERVE": 0.25}
        settings.update(overrides)
        return make_model(**settings)

    return _make


def fly(model, direction, speed, uav=0):
    """Flies one UAV of the team a single step, and reports the fuel it burned doing so."""
    drone = model.uavs[uav]
    before = drone.fuel
    drone.selected_dir = direction
    drone.selected_speed = speed
    drone.advance()
    return before - drone.fuel


# --- the extension is off by default ----------------------------------------


def test_fuel_is_not_burned_when_the_extension_is_off(fleet):
    model = fleet(ACTIVATE_FUEL=False)
    drone = model.uavs[0]

    assert fly(model, ACTION_RIGHT, 3) == 0
    assert drone.fuel == config.UAV_FUEL
    assert not drone.is_out_of_fuel()


def test_an_empty_tank_is_harmless_when_the_extension_is_off(fleet):
    model = fleet(ACTIVATE_FUEL=False)
    drone = model.uavs[0]
    drone.fuel = 0.0

    model.resolve_fuel()

    assert drone.is_alive()
    assert model.uavs_out_of_fuel == 0


def test_observations_report_no_fuel_when_the_extension_is_off(fleet):
    model = fleet(ACTIVATE_FUEL=False)

    observation = model.uavs[0].observe()

    # None rather than a number is what tells a policy fuel is not being tracked at all
    assert observation.fuel is None
    assert observation.fuel_capacity is None
    assert observation.fuel_fraction() == 1.0
    assert not observation.low_fuel()


# --- what a step costs ------------------------------------------------------


def test_a_uav_starts_with_a_full_tank(fleet):
    model = fleet(UAV_FUEL=80.0)

    assert model.uavs[0].fuel == 80.0
    assert model.uavs[0].has_full_tank()


def test_holding_position_costs_the_idle_burn_alone(fleet):
    model = fleet()

    assert fly(model, ACTION_STAY, 0) == pytest.approx(1.0)


def test_flying_costs_the_idle_burn_plus_the_distance(fleet):
    model = fleet()

    # 1 idle + 1.0 * 3 ** 1.5
    assert fly(model, ACTION_RIGHT, 3) == pytest.approx(1.0 + 3 ** 1.5)


def test_speed_costs_more_than_the_same_ground_flown_slowly(fleet):
    """The point of the exponent: a dash costs more than the same distance covered a cell at a time."""
    dash = fleet()
    burned_at_speed = fly(dash, ACTION_RIGHT, 4)

    cruise = fleet()
    burned_slowly = sum(fly(cruise, ACTION_RIGHT, 1) for _ in range(4))

    assert burned_at_speed > burned_slowly
    assert burned_at_speed == pytest.approx(1.0 + 4 ** 1.5)
    assert burned_slowly == pytest.approx(4 * (1.0 + 1.0))


def test_a_flat_exponent_makes_speed_and_distance_cost_the_same(fleet):
    dash = fleet(UAV_FUEL_SPEED_EXPONENT=1.0, UAV_FUEL_IDLE_BURN=0.0)
    cruise = fleet(UAV_FUEL_SPEED_EXPONENT=1.0, UAV_FUEL_IDLE_BURN=0.0)

    assert fly(dash, ACTION_RIGHT, 4) == pytest.approx(
        sum(fly(cruise, ACTION_RIGHT, 1) for _ in range(4)))


def test_only_the_cells_actually_covered_are_charged(fleet):
    """A UAV stopped by the edge of the grid does not pay for the flight it did not make."""
    model = fleet()
    model.grid.move_agent(model.uavs[0], (7, 4))  # two cells short of the right hand edge of a 9x9 grid

    burned = fly(model, ACTION_RIGHT, 5)

    assert model.uavs[0].pos == (8, 4)
    assert burned == pytest.approx(1.0 + 1 ** 1.5)


def test_dumping_water_costs_the_idle_burn(fleet):
    model = fleet(count=1, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(0, 0))
    drone = model.uavs[0]
    model.grid.move_agent(drone, (5, 5))  # off the base, or the idle burn would be waived

    assert fly(model, config.ACTION_DUMP_WATER, 0) == pytest.approx(1.0)


def test_the_tank_never_goes_below_zero(fleet):
    model = fleet()
    drone = model.uavs[0]
    drone.fuel = 0.5

    burned = fly(model, ACTION_RIGHT, 5)

    assert burned == pytest.approx(0.5)
    assert drone.fuel == 0.0
    assert drone.is_out_of_fuel()


def test_a_uav_parked_on_the_base_burns_nothing(fleet):
    model = fleet(count=1, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2))
    drone = model.uavs[0]
    model.grid.move_agent(drone, (2, 2))

    assert fly(model, ACTION_STAY, 0) == 0
    assert drone.fuel == config.UAV_FUEL


# --- running out ------------------------------------------------------------


def test_an_empty_tank_costs_every_health_point_and_destroys_the_uav(fleet):
    model = fleet(count=1, UAV_HP=3)
    drone = model.uavs[0]
    drone.fuel = 0.0

    model.resolve_fuel()

    assert drone.hp == 0
    assert not drone.is_alive()
    assert model.uavs_out_of_fuel == 1
    assert model.uavs_lost == 1
    # destroyed means off the grid and out of the scheduler, but still a record of the team that started
    assert drone.pos is None
    assert drone not in model.schedule.agents
    assert drone in model.uavs
    assert model.active_uavs() == []


def test_a_uav_runs_dry_in_flight_over_a_run(fleet):
    """The whole loop, through model.step(): fly until the tank is empty and be destroyed for it."""
    model = fleet(count=1, UAV_FUEL=12.0,
                  policy=ScriptedPolicy({0: Action(ACTION_RIGHT, 1)}))
    drone = model.uavs[0]

    for _ in range(20):
        model.step()
        if not drone.is_alive():
            break

    assert not drone.is_alive()
    assert drone.fuel == 0.0
    assert model.uavs_out_of_fuel == 1


def test_a_uav_with_fuel_left_is_not_touched(fleet):
    model = fleet(count=1)

    model.resolve_fuel()

    assert model.uavs[0].is_alive()
    assert model.uavs_out_of_fuel == 0


def test_a_uav_destroyed_by_a_collision_is_not_counted_as_out_of_fuel_too(fleet):
    """A UAV that collides fatally and runs dry on the same step is one loss, against the collision."""
    model = fleet(count=2, UAV_HP=1, UAV_COLLISION_DAMAGE_MEAN=1.0)
    for drone in model.uavs:
        model.grid.move_agent(drone, (4, 4))  # stacked, so both collide
        drone.fuel = 0.0

    model.resolve_collisions()
    model.resolve_fuel()

    assert model.uavs_lost == 2
    assert model.uavs_out_of_fuel == 0  # the collision got there first
    assert model.collisions == 1


# --- refuelling at the base -------------------------------------------------


def test_the_base_refuels_a_uav_that_lands_on_it(fleet):
    model = fleet(count=1, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2),
                  BASE_REFILL_STEPS=1, BASE_REFUEL_STEPS=2)
    drone = model.uavs[0]
    model.grid.move_agent(drone, (2, 2))
    drone.fuel = 10.0

    # a visit takes max(BASE_REFILL_STEPS, BASE_REFUEL_STEPS) steps, so the first one is not enough
    model.base.serve(drone)
    assert drone.fuel == 10.0

    model.base.serve(drone)
    assert drone.fuel == config.UAV_FUEL
    assert drone.has_full_tank()


def test_the_base_serves_water_and_fuel_in_one_visit(fleet):
    model = fleet(count=1, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2),
                  BASE_REFILL_STEPS=1, BASE_REFUEL_STEPS=1)
    drone = model.uavs[0]
    model.grid.move_agent(drone, (2, 2))
    drone.water = 0
    drone.fuel = 10.0

    model.base.serve(drone)

    assert drone.has_water()
    assert drone.has_full_tank()


def test_a_uav_wanting_only_fuel_still_takes_a_slot(fleet):
    """Full of water but short of fuel is a reason to be served, and to make a teammate queue."""
    model = fleet(count=2, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2),
                  BASE_CAPACITY=1, BASE_REFUEL_STEPS=2)
    thirsty, waiting = model.uavs
    for drone in (thirsty, waiting):
        model.grid.move_agent(drone, (2, 2))
    thirsty.fuel = 10.0          # full of water, wants fuel
    waiting.water = 0            # wants water

    assert model.base.needs_service(thirsty)
    model.base.serve(thirsty)
    model.base.serve(waiting)

    assert thirsty.unique_id in model.base.serving
    assert waiting.unique_id not in model.base.serving  # the one slot was taken
    assert not waiting.has_water()


def test_a_full_uav_is_not_served(fleet):
    model = fleet(count=1, ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2))
    drone = model.uavs[0]
    model.grid.move_agent(drone, (2, 2))

    assert not model.base.needs_service(drone)
    assert model.base.serve(drone) is False


def test_a_visit_takes_the_refill_time_when_fuel_is_off(fleet):
    """With the extension off the base behaves exactly as it always did: water only, on its own timer."""
    model = fleet(count=1, ACTIVATE_FUEL=False, ACTIVATE_FIREFIGHTING=True,
                  BASE_POSITION=(2, 2), BASE_SIZE=(2, 2), BASE_REFILL_STEPS=1, BASE_REFUEL_STEPS=9)
    drone = model.uavs[0]
    model.grid.move_agent(drone, (2, 2))
    drone.water = 0
    drone.fuel = 10.0

    assert model.base.service_steps() == 1
    model.base.serve(drone)

    assert drone.has_water()
    assert drone.fuel == 10.0  # untouched: nothing refuels when the extension is off


# --- what a policy is told --------------------------------------------------


def test_observations_report_the_tank(fleet):
    model = fleet(count=1, UAV_FUEL=100.0)
    model.uavs[0].fuel = 40.0

    observation = model.uavs[0].observe()

    assert observation.fuel == 40.0
    assert observation.fuel_capacity == 100.0
    assert observation.fuel_fraction() == pytest.approx(0.4)
    assert not observation.low_fuel()


def test_low_fuel_is_reported_at_the_reserve(observation):
    at_reserve = observation(pos=(4, 4), fuel=25.0, fuel_capacity=100.0)
    above_it = observation(pos=(4, 4), fuel=26.0, fuel_capacity=100.0)

    assert at_reserve.low_fuel()      # UAV_FUEL_RESERVE is 0.25 in config.py
    assert not above_it.low_fuel()


# --- the firefighter policy -------------------------------------------------


def test_the_firefighter_breaks_off_for_home_when_low_on_fuel(observation, uav_speed):
    """Low on fuel outranks the fire: the UAV turns for the base with its water still aboard."""
    uav_speed(5)
    policy = FirefighterPolicy()
    low = observation(pos=(4, 4), burning=[(6, 4)], has_water=True,
                      base_pos=(0, 4), base_cells=[(0, 4)], fuel=10.0, fuel_capacity=100.0)

    action, = policy.select_actions([low])

    assert action.direction == config.ACTION_LEFT  # toward the base at (0, 4), away from the fire


def test_the_firefighter_attacks_the_fire_with_fuel_to_spare(observation, uav_speed):
    uav_speed(5)
    policy = FirefighterPolicy()
    # the fire is kept outside WATER_DROP_RADIUS, so the UAV flies at it rather than dumping where it is
    fuelled = observation(pos=(4, 4), burning=[(8, 4)], has_water=True,
                          base_pos=(0, 4), base_cells=[(0, 4)], fuel=90.0, fuel_capacity=100.0)

    action, = policy.select_actions([fuelled])

    assert action.direction == config.ACTION_RIGHT  # toward the fire at (8, 4)


def test_the_firefighter_waits_on_the_base_until_it_is_refuelled(observation, uav_speed):
    """Landing is not enough: a visit takes BASE_REFUEL_STEPS, so the UAV has to stay for them.

    Flying off the moment it arrived would leave it as dry as it landed, so low_fuel() keeps holding it
    there until the base has filled the tank, exactly as an empty one waits for its water.
    """
    uav_speed(5)
    policy = FirefighterPolicy()
    home = observation(pos=(0, 4), burning=[(8, 4)], has_water=True,
                       base_pos=(0, 4), base_cells=[(0, 4)], fuel=10.0, fuel_capacity=100.0)

    action, = policy.select_actions([home])

    assert action == Action.stay()


def test_the_firefighter_leaves_the_base_once_the_tank_is_full(observation, uav_speed):
    uav_speed(5)
    policy = FirefighterPolicy()
    refuelled = observation(pos=(0, 4), burning=[(8, 4)], has_water=True,
                            base_pos=(0, 4), base_cells=[(0, 4)], fuel=100.0, fuel_capacity=100.0)

    action, = policy.select_actions([refuelled])

    assert action.direction == config.ACTION_RIGHT  # back out to the fire
