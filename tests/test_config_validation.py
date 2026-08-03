"""Tests for config.validate().

The bounds documented against each setting in config.py used to be advisory: an out of bounds value
either ran and quietly gave nonsense, or failed much later and far from its cause. These check that the
settings whose bounds actually matter are refused at the start of a run instead, and that a valid
configuration is left alone.
"""

# python libraries

import pytest

# own python modules

import config


# --- a good configuration ---------------------------------------------------


def test_the_shipped_configuration_is_valid():
    """Whatever config.py is currently set to has to pass its own checks."""
    config.validate()


def test_a_model_can_still_be_built(make_model):
    """validate() runs from WildFireModel.__init__, so a normal model is proof it accepts the defaults."""
    assert make_model() is not None


# --- forest area ------------------------------------------------------------


@pytest.mark.parametrize("setting, value", [
    ("BATCH_SIZE", 0),
    ("WIDTH", 0),
    ("HEIGHT", -1),
    ("BURNING_RATE", 0),
    ("DENSITY_PROB", 1.5),
    ("DENSITY_PROB", -0.1),
])
def test_out_of_bounds_forest_settings_are_refused(sim_config, setting, value):
    sim_config(**{setting: value})
    with pytest.raises(ValueError, match=setting):
        config.validate()


def test_fire_spread_speed_of_zero_is_refused(sim_config):
    """It would divide by zero inside Fire.step(), which is a long way from the setting."""
    sim_config(FIRE_SPREAD_SPEED=0)
    with pytest.raises(ValueError, match="FIRE_SPREAD_SPEED"):
        config.validate()


def test_a_fractional_fire_spread_speed_is_refused(sim_config):
    """A fraction never satisfies the integer modulo in Fire.step(), which freezes the fire silently."""
    sim_config(FIRE_SPREAD_SPEED=0.5)
    with pytest.raises(ValueError, match="FIRE_SPREAD_SPEED"):
        config.validate()


def test_inverted_cell_fuel_limits_are_refused(sim_config):
    """randint(bottom, upper) raises once per cell otherwise, which buries the real problem."""
    sim_config(FUEL_BOTTOM_LIMIT=10, FUEL_UPPER_LIMIT=5)
    with pytest.raises(ValueError, match="FUEL_BOTTOM_LIMIT"):
        config.validate()


# --- wind -------------------------------------------------------------------


def test_an_unknown_fixed_wind_direction_is_refused(sim_config):
    sim_config(ACTIVATE_WIND=True, FIXED_WIND=True, WIND_DIRECTION="northwest")
    with pytest.raises(ValueError, match="WIND_DIRECTION"):
        config.validate()


def test_an_unknown_composed_wind_direction_is_refused(sim_config):
    sim_config(ACTIVATE_WIND=True, FIXED_WIND=False, SECOND_DIR="up")
    with pytest.raises(ValueError, match="SECOND_DIR"):
        config.validate()


def test_wind_settings_are_ignored_when_the_wind_is_off(sim_config):
    """Nothing reads them, so a stale direction is not worth refusing a run over."""
    sim_config(ACTIVATE_WIND=False, WIND_DIRECTION="nonsense", MU=99)
    config.validate()


@pytest.mark.parametrize("setting", ["MU", "FIRST_DIR_PROB"])
def test_wind_probabilities_outside_zero_to_one_are_refused(sim_config, setting):
    sim_config(ACTIVATE_WIND=True, FIXED_WIND=False, **{setting: 1.5})
    with pytest.raises(ValueError, match=setting):
        config.validate()


def test_the_composed_wind_settings_exist_under_fixed_wind():
    """They used to be defined inside 'if not FIXED_WIND', which made them un-overridable."""
    for name in ("FIRST_DIR", "SECOND_DIR", "FIRST_DIR_PROB"):
        assert hasattr(config, name)


# --- UAVs -------------------------------------------------------------------


def test_a_team_larger_than_the_grid_is_refused(sim_config):
    sim_config(WIDTH=4, HEIGHT=4, NUM_AGENTS=17)
    with pytest.raises(ValueError, match="do not fit"):
        config.validate()


def test_a_team_that_exactly_fills_the_grid_is_allowed(sim_config):
    sim_config(WIDTH=4, HEIGHT=4, NUM_AGENTS=16)
    config.validate()


def test_the_probability_map_refuses_a_team(sim_config):
    """A UAV gets no 'Layer' in the probability map portrayal, so the canvas throws KeyError."""
    sim_config(PROBABILITY_MAP=True, NUM_AGENTS=2)
    with pytest.raises(ValueError, match="PROBABILITY_MAP"):
        config.validate()


def test_the_probability_map_is_fine_without_a_team(sim_config):
    sim_config(PROBABILITY_MAP=True, NUM_AGENTS=0)
    config.validate()


@pytest.mark.parametrize("setting, value", [
    ("N_ACTIONS", 3),
    ("UAV_SPEED", -1),
    ("UAV_OBSERVATION_RADIUS", -1),
    ("UAV_HP", 0),
    ("SECURITY_DISTANCE", -1),
])
def test_out_of_bounds_uav_settings_are_refused(sim_config, setting, value):
    sim_config(**{setting: value})
    with pytest.raises(ValueError, match=setting):
        config.validate()


# --- extensions -------------------------------------------------------------


@pytest.mark.parametrize("setting, value", [
    ("UAV_FUEL", 0),
    ("UAV_FUEL_IDLE_BURN", -1),
    ("UAV_FUEL_RESERVE", 1.5),
])
def test_out_of_bounds_fuel_settings_are_refused(sim_config, setting, value):
    sim_config(ACTIVATE_FUEL=True, **{setting: value})
    with pytest.raises(ValueError, match=setting):
        config.validate()


def test_fuel_settings_are_ignored_when_the_extension_is_off(sim_config):
    sim_config(ACTIVATE_FUEL=False, UAV_FUEL=0)
    config.validate()


@pytest.mark.parametrize("setting, value", [
    ("BHP", 0),
    ("BASE_CAPACITY", 0),
    ("UAV_WATER_CAPACITY", 0),
    ("WATER_DROP_RADIUS", -1),
    ("WATER_EXTINGUISH_PROB_CENTRE", 1.5),
    ("SPONTANEOUS_REIGNITION_PROB", -0.5),
    ("NUM_OUT_BUILDINGS", -1),
    ("OUT_BUILDING_HP", 0),
])
def test_out_of_bounds_firefighting_settings_are_refused(sim_config, setting, value):
    sim_config(ACTIVATE_FIREFIGHTING=True, **{setting: value})
    with pytest.raises(ValueError, match=setting):
        config.validate()


def test_firefighting_settings_are_ignored_when_the_extension_is_off(sim_config):
    sim_config(ACTIVATE_FIREFIGHTING=False, BHP=0, WATER_DROP_RADIUS=-5)
    config.validate()


def test_fuel_without_a_base_to_refuel_at_is_allowed(sim_config):
    """Documented as a hard endurance limit on the run rather than a mistake."""
    sim_config(ACTIVATE_FUEL=True, ACTIVATE_FIREFIGHTING=False)
    config.validate()


# --- reporting --------------------------------------------------------------


def test_every_problem_is_reported_at_once(sim_config):
    """A badly set up run should be fixable in one pass, not one error at a time."""
    sim_config(BATCH_SIZE=0, UAV_HP=0, DENSITY_PROB=2.0)

    with pytest.raises(ValueError) as raised:
        config.validate()

    message = str(raised.value)
    assert "BATCH_SIZE" in message
    assert "UAV_HP" in message
    assert "DENSITY_PROB" in message
