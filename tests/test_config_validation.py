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
    ("UAV_FUEL_WATER_PENALTY", -0.1),
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


@pytest.mark.parametrize("setting, value", [
    ("UAV_POSITION_BIAS_MAX", -1),
    ("UAV_POSITION_NOISE_MAX", -1),
    ("UAV_POSITION_BIAS_MAX", 1.5),
    ("UAV_POSITION_NOISE_MAX", 1.5),
])
def test_out_of_bounds_position_error_settings_are_refused(sim_config, setting, value):
    sim_config(ACTIVATE_POSITION_ERROR=True, **{setting: value})
    with pytest.raises(ValueError, match=setting):
        config.validate()


def test_position_error_settings_are_ignored_when_the_extension_is_off(sim_config):
    sim_config(ACTIVATE_POSITION_ERROR=False, UAV_POSITION_BIAS_MAX=-5, UAV_POSITION_NOISE_MAX=-5)
    config.validate()


def test_a_positioning_error_of_no_magnitude_at_all_is_allowed(sim_config):
    """The extension switched on with nothing to do, which is the control arm of a sweep over magnitudes."""
    sim_config(ACTIVATE_POSITION_ERROR=True, UAV_POSITION_BIAS_MAX=0, UAV_POSITION_NOISE_MAX=0)
    config.validate()


# --- managing system --------------------------------------------------------


@pytest.mark.parametrize("managing", ["heuristic", "remote"])
@pytest.mark.parametrize("setting, value", [
    ("ADAPTATION_PERIOD", 0),
    ("ADAPTATION_PERIOD", 1.5),
    ("ADAPTATION_HYSTERESIS", 0),
    ("DEFAULT_UAV_POLICY", ""),
    ("DEFAULT_UAV_POLICY", None),
    ("BASE_SENSOR_RADIUS", -1),
    ("BASE_THREAT_RADIUS", 0),
    ("MANAGING_CROWDED_SPEED_CAP", -1),
    ("MANAGING_KNOWLEDGE_HISTORY", 0),
])
def test_out_of_bounds_managing_settings_are_refused(sim_config, managing, setting, value):
    # they are the same settings wherever the managing system lives, so both are checked
    sim_config(MANAGING_SYSTEM=managing, **{setting: value})
    with pytest.raises(ValueError, match=setting):
        config.validate()


# an unknown name is not this module's business: MANAGING_SYSTEM names a managing system registered in
# sim/managing/systems.py, and config.py cannot import that package to look one up, because it imports
# config.py. The name is resolved when the managing system is built, which raises listing the ones that
# exist -- see tests/managing/test_systems.py. What is checked here is that it is a name at all.
@pytest.mark.parametrize("value", [None, "", 3])
def test_a_managing_system_that_is_not_a_name_is_refused(sim_config, value):
    sim_config(MANAGING_SYSTEM=value)
    with pytest.raises(ValueError, match="MANAGING_SYSTEM"):
        config.validate()


# 'remote' says the managing system being built is one that lives on a server, which is what puts these
# settings in play. build_managing_system() passes it, because the selected managing system is what knows.
@pytest.mark.parametrize("setting, value", [
    ("MANAGING_SYSTEM_URL", "not-a-url"),
    ("MANAGING_SYSTEM_TIMEOUT", 0),
])
def test_out_of_bounds_remote_settings_are_refused(sim_config, setting, value):
    sim_config(MANAGING_SYSTEM="remote", **{setting: value})
    with pytest.raises(ValueError, match=setting):
        config.validate(remote=True)


def test_the_remote_settings_are_ignored_by_a_local_managing_system(sim_config):
    sim_config(MANAGING_SYSTEM="heuristic", MANAGING_SYSTEM_URL="nonsense", MANAGING_SYSTEM_TIMEOUT=-1)
    config.validate()


def test_managing_settings_are_ignored_when_there_is_no_managing_system(sim_config):
    sim_config(MANAGING_SYSTEM="none", ADAPTATION_PERIOD=0, MANAGING_SYSTEM_URL="nonsense")
    config.validate()


# the web interface can start a managing system for one model without touching config.py, and its settings
# then have to be checked even though the file says they are unused
def test_the_check_can_be_asked_for_a_managing_system_the_file_does_not_have(sim_config):
    sim_config(MANAGING_SYSTEM="none", ADAPTATION_PERIOD=0)
    config.validate()                                   # as configured, nothing reads it
    with pytest.raises(ValueError, match="ADAPTATION_PERIOD"):
        config.validate(managing="heuristic")           # ... but this caller is about to


# config.py cannot import the policy package to look the name up, because the policy package imports
# config. The name is resolved when the model is built instead, which is where the useful error lives.
def test_an_unknown_default_policy_is_caught_when_the_model_is_built(sim_config):
    sim_config(MANAGING_SYSTEM="heuristic", DEFAULT_UAV_POLICY="no-such-policy")
    config.validate()   # the name is a string, so validate() is satisfied

    from sim.policy import SuperPolicy

    with pytest.raises(KeyError, match="available"):
        SuperPolicy()


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
