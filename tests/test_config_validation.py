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


def test_an_unknown_wind_direction_is_refused(sim_config):
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=["NORTH", "up"])
    with pytest.raises(ValueError, match="WIND_DIRECTION"):
        config.validate()


def test_a_direction_that_is_not_even_a_name_is_refused(sim_config):
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=[7])
    with pytest.raises(ValueError, match="WIND_DIRECTION"):
        config.validate()


def test_something_that_is_not_a_list_of_directions_is_refused(sim_config):
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION={"NORTH": 1})
    with pytest.raises(ValueError, match="WIND_DIRECTION"):
        config.validate()


@pytest.mark.parametrize("setting", ["SOUTH", "south", ["SOUTH"], ["south", "NORTH_WEST"]])
def test_the_forms_a_direction_may_be_written_in_are_accepted(sim_config, setting):
    """A bare string is what --set WIND_DIRECTION=SOUTH produces, and lower case is what config.py
    shipped for years -- the sweeps under experiments/ still pass it that way."""
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=setting)
    config.validate()


@pytest.mark.parametrize("setting", [None, []])
def test_no_directions_at_all_means_no_wind_rather_than_a_broken_run(sim_config, setting):
    sim_config(ACTIVATE_WIND=True, WIND_DIRECTION=setting)
    config.validate()


def test_wind_settings_are_ignored_when_the_wind_is_off(sim_config):
    """Nothing reads them, so a stale direction is not worth refusing a run over."""
    sim_config(ACTIVATE_WIND=False, WIND_DIRECTION="nonsense", MU=99, WIND_VARIABILITY=-3)
    config.validate()


def test_a_wind_strength_outside_zero_to_one_is_refused(sim_config):
    sim_config(ACTIVATE_WIND=True, MU=1.5)
    with pytest.raises(ValueError, match="MU"):
        config.validate()


@pytest.mark.parametrize("setting", [0, -1, 2.5, "20", True])
def test_a_variability_that_is_not_a_positive_whole_number_of_steps_is_refused(sim_config, setting):
    # True is in the list because bool is a subclass of int, and WIND_VARIABILITY = True would otherwise
    # pass the check and quietly mean "turn every step"
    sim_config(ACTIVATE_WIND=True, WIND_VARIABILITY=setting)
    with pytest.raises(ValueError, match="WIND_VARIABILITY"):
        config.validate()


def test_a_variability_of_none_is_accepted_as_a_wind_that_never_turns(sim_config):
    sim_config(ACTIVATE_WIND=True, WIND_VARIABILITY=None)
    config.validate()


# --- smoke ------------------------------------------------------------------


def test_a_wind_strength_for_smoke_outside_zero_to_one_is_refused(sim_config):
    sim_config(ACTIVATE_SMOKE=True, SMOKE_MU=1.5)
    with pytest.raises(ValueError, match="SMOKE_MU"):
        config.validate()


def test_a_negative_drift_radius_is_refused(sim_config):
    sim_config(ACTIVATE_SMOKE=True, SMOKE_DRIFT_RADIUS=-1)
    with pytest.raises(ValueError, match="SMOKE_DRIFT_RADIUS"):
        config.validate()


@pytest.mark.parametrize("threshold", [0.0, 1.5])
def test_an_occlusion_threshold_outside_its_range_is_refused(sim_config, threshold):
    """Zero would bury the whole grid the moment one cell smoked, since every cell out of range is at 0."""
    sim_config(ACTIVATE_SMOKE=True, SMOKE_OCCLUSION_THRESHOLD=threshold)
    with pytest.raises(ValueError, match="SMOKE_OCCLUSION_THRESHOLD"):
        config.validate()


def test_the_plume_settings_are_ignored_when_smoke_is_off(sim_config):
    """Nothing raises smoke, so nothing reads them and a stale value is not worth refusing a run over."""
    sim_config(ACTIVATE_SMOKE=False, SMOKE_MU=99, SMOKE_DRIFT_RADIUS=-4, SMOKE_OCCLUSION_THRESHOLD=0)
    config.validate()


def test_occlusion_without_any_smoke_to_see_through_is_allowed(sim_config):
    """The extension switched on with nothing to raise smoke: the control arm a sweep over it wants.

    The same latitude ACTIVATE_FUEL gets without ACTIVATE_FIREFIGHTING, and the positioning error gets at
    zero magnitude.
    """
    sim_config(ACTIVATE_SMOKE=False, SMOKE_OCCLUDES_OBSERVATION=True)
    config.validate()


def test_smoke_carried_less_far_than_the_fire_is_allowed(sim_config):
    """SMOKE_MU is meant to sit above MU, and that is documented rather than enforced.

    A sweep showing that smoke drifting harder than the fire is what costs the team its monitoring has to
    be able to run the other side of the boundary to say so.
    """
    sim_config(ACTIVATE_SMOKE=True, ACTIVATE_WIND=True, MU=0.9, SMOKE_MU=0.1, SMOKE_DRIFT_RADIUS=1)
    config.validate()


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
