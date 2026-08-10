"""Tests for the parameter sweep tool.

The tool's whole value is that a row in its CSV says which configuration produced it. The results it
merges come from `headless.py`, whose JSON records the metrics but not the `--set` values, so the join is
done here from the arm the tool launched -- and a join done in the tool rather than by the data is exactly
the kind that goes wrong silently, putting the right numbers under the wrong parameters. Most of what
follows is about that.

The rest is the statistics and the bisection, neither of which needs a simulation to test: `run_arm` is
replaced with a synthetic response so the search can be driven over a function whose answer is known.
"""

# python libraries

import csv
import json

import pytest

# own python modules

from tools import sweep


# --- the axis product -------------------------------------------------------


def test_the_arms_are_the_cartesian_product_of_the_axes():
    arms = sweep.build_arms({}, {"BHP": [2, 3], "FIRE_SPREAD_SPEED": [1, 2]})
    assert [arm.params for arm in arms] == [
        {"BHP": 2, "FIRE_SPREAD_SPEED": 1},
        {"BHP": 2, "FIRE_SPREAD_SPEED": 2},
        {"BHP": 3, "FIRE_SPREAD_SPEED": 1},
        {"BHP": 3, "FIRE_SPREAD_SPEED": 2},
    ]


def test_every_arm_carries_the_base_settings_underneath_its_own():
    arms = sweep.build_arms({"WIDTH": 100, "HEIGHT": 100}, {"BHP": [2, 3]})
    assert arms[0].settings == {"WIDTH": 100, "HEIGHT": 100, "BHP": 2}
    assert arms[1].settings == {"WIDTH": 100, "HEIGHT": 100, "BHP": 3}


def test_an_axis_value_overrides_a_base_setting_of_the_same_name():
    # so that a scan can pin a knob in --base for most of its arms and still vary it on one axis, rather
    # than the two silently disagreeing about which value reached the simulation
    arms = sweep.build_arms({"BHP": 5}, {"BHP": [2]})
    assert arms[0].settings["BHP"] == 2


def test_no_axes_is_a_single_arm_of_the_base_settings():
    arms = sweep.build_arms({"WIDTH": 100}, {})
    assert len(arms) == 1 and arms[0].settings == {"WIDTH": 100} and arms[0].label == "(base)"


def test_arms_get_distinct_filenames():
    arms = sweep.build_arms({}, {"BHP": [2, 3], "FIRE_SPREAD_SPEED": [1, 2]})
    assert len({arm.slug for arm in arms}) == len(arms)


# --- derived axes -----------------------------------------------------------


def test_a_plain_constant_stands_for_itself():
    assert sweep.expand("BHP", 3) == {"BHP": 3}


def test_the_extinguish_scale_moves_both_ends_of_the_falloff():
    # the point of the derived axis: one number to bisect on, and the centre stays stronger than the edge
    assert sweep.expand("EXTINGUISH_SCALE", 1.0) == {"WATER_EXTINGUISH_PROB_CENTRE": 0.95,
                                                     "WATER_EXTINGUISH_PROB_EDGE": 0.60}
    half = sweep.expand("EXTINGUISH_SCALE", 0.5)
    assert half["WATER_EXTINGUISH_PROB_CENTRE"] == 0.475
    assert half["WATER_EXTINGUISH_PROB_EDGE"] == 0.30


@pytest.mark.parametrize("scale", [0.0, 0.35, 0.7, 1.0])
def test_the_extinguish_scale_stays_inside_the_bounds_config_validates(scale):
    for value in sweep.expand("EXTINGUISH_SCALE", scale).values():
        assert 0.0 <= value <= 1.0


# --- the command handed to headless.py --------------------------------------


@pytest.fixture
def options():
    """The parsed options for a small scan, as build_parser() would produce them."""
    parsed = sweep.build_parser().parse_args(
        ["scan", "--policy", "firefighter", "--runs", "5", "--seed", "7",
         "--axis", "BHP=2,3", "--out", "unused"])
    parsed.base = dict(sweep.parse_override(text) for text in parsed.base)
    parsed.axes = dict(sweep.parse_axis(text) for text in parsed.axis)
    return parsed


def test_the_arm_settings_reach_headless_as_set_arguments(options, tmp_path):
    arm = sweep.Arm(params={"BHP": 3}, settings={"BHP": 3, "WIDTH": 100})
    command = sweep.arm_command(arm, options, tmp_path / "arm.json")
    assert "--set" in command and "BHP=3" in command and "WIDTH=100" in command
    assert command[command.index("--policy") + 1] == "firefighter"
    assert command[command.index("--seed") + 1] == "7"


def test_the_run_length_cannot_be_set_with_steps(options, tmp_path):
    """`--steps` is not offered, and must not be smuggled into the command either.

    It is the trap that produced a wrong answer once already: `headless.py --steps` used to be a separate
    count of runner iterations, and the model stops itself at its own BATCH_SIZE, so any --steps above it
    did nothing at all -- a sweep of 120, 150 and 200 came back with three identical win rates, which
    reads exactly like a run length that does not matter. headless.py now treats --steps as an alias for
    BATCH_SIZE, so the flag no longer lies; the sweep still refuses it, because one axis wants one name
    and an arm that set both would be setting the run length twice.
    """
    with pytest.raises(SystemExit):
        sweep.build_parser().parse_args(["scan", "--axis", "BHP=2", "--steps", "200"])

    arm = sweep.Arm(params={"BATCH_SIZE": 150}, settings={"BATCH_SIZE": 150})
    command = sweep.arm_command(arm, options, tmp_path / "arm.json")
    assert "--steps" not in command
    assert "BATCH_SIZE=150" in command


@pytest.mark.parametrize("value, text", [
    (3, "3"), (0.65, "0.65"), (True, "True"), (None, "None"), ((1, 2), "(1, 2)"),
    # a string goes bare, because --set falls back to the raw text when the literal will not parse; repr()
    # would send WIND_DIRECTION='south' with the quotes attached
    ("south", "south"), ("random", "random"),
])
def test_values_are_rendered_the_way_set_reads_them_back(value, text):
    assert sweep.format_value(value) == text


def test_every_rendered_value_survives_the_round_trip_through_set():
    for value in [3, 0.65, True, None, (1, 2), "south"]:
        rendered = sweep.format_value(value)
        assert sweep.parse_override(f"NAME={rendered}") == ("NAME", value)


# --- the join ---------------------------------------------------------------


def fake_results(count, wins):
    """`headless.py --output` JSON for `count` runs, `wins` of which were won."""
    return [{"run_id": index, "seed": 1000 + index, "collisions": index,
             "outcome": "WON" if index < wins else "LOST", "error": None}
            for index in range(count)]


def test_a_run_is_tagged_with_the_arm_that_produced_it(options, tmp_path, monkeypatch):
    arm = sweep.Arm(params={"BHP": 3}, settings={"BHP": 3})

    def fake_run(command, **kwargs):
        output = command[command.index("--output") + 1]
        with open(output, "w") as handle:
            json.dump(fake_results(4, wins=1), handle)
        return type("Completed", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(sweep.subprocess, "run", fake_run)
    rows = sweep.run_arm(arm, options, tmp_path)

    assert len(rows) == 4
    assert all(row["BHP"] == 3 for row in rows)
    assert all(row["policy"] == "firefighter" and row["arm"] == "BHP=3" for row in rows)
    # and the run's own fields survive the tagging
    assert [row["collisions"] for row in rows] == [0, 1, 2, 3]


def test_a_result_field_cannot_overwrite_the_arm_it_came_from(options, tmp_path, monkeypatch):
    # RunResult carries a `managing` boolean of its own, and the first version of this join let it land on
    # top of the column naming the arm. Any collision has to fall the other way: the identity of a row is
    # the whole reason the CSV is worth having, and a result that quietly renames its own arm is worse than
    # no join at all.
    def fake_run(command, **kwargs):
        output = command[command.index("--output") + 1]
        with open(output, "w") as handle:
            json.dump([{"arm": "something else", "BHP": 99, "managing": False, "outcome": "WON"}], handle)
        return type("Completed", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(sweep.subprocess, "run", fake_run)
    row = sweep.run_arm(sweep.Arm(params={"BHP": 3}, settings={"BHP": 3}), options, tmp_path)[0]

    assert row["arm"] == "BHP=3" and row["BHP"] == 3
    assert row["managing_asked"] == "none"      # what the sweep asked for
    assert row["managing"] is False             # what the run reported, kept under its own name


def test_a_rejected_configuration_is_raised_rather_than_skipped(options, tmp_path, monkeypatch):
    # headless.py already records a run that threw as an error in its results, so a non-zero exit means the
    # configuration itself was refused. Dropping the arm would leave a hole in the surface with nothing
    # marking it.
    monkeypatch.setattr(sweep.subprocess, "run",
                        lambda *a, **k: type("Completed", (), {"returncode": 2, "stderr": "bad knob"})())
    with pytest.raises(RuntimeError, match="bad knob"):
        sweep.run_arm(sweep.Arm(params={"BHP": 3}, settings={"BHP": 3}), options, tmp_path)


def test_the_csv_puts_each_arms_parameters_on_its_own_rows(tmp_path):
    rows = ([{"arm": "BHP=2", "BHP": 2, "run_id": index, "outcome": "LOST"} for index in range(3)]
            + [{"arm": "BHP=3", "BHP": 3, "run_id": index, "outcome": "WON"} for index in range(3)])
    path = tmp_path / "runs.csv"
    sweep.write_csv(path, rows)

    with open(path, newline="") as handle:
        written = list(csv.DictReader(handle))

    assert len(written) == 6
    assert [row["BHP"] for row in written] == ["2", "2", "2", "3", "3", "3"]
    assert {row["outcome"] for row in written if row["BHP"] == "3"} == {"WON"}


def test_the_csv_carries_columns_that_only_some_runs_have(tmp_path):
    # a result carries different fields depending on which extensions were on, and a sweep that varies one
    # produces arms with different fields. The union has to be written, or the extra columns are dropped
    # for every row without a word about it.
    rows = [{"arm": "a", "run_id": 0}, {"arm": "b", "run_id": 1, "fuel_remaining": 12.5}]
    path = tmp_path / "runs.csv"
    columns = sweep.write_csv(path, rows)

    assert "fuel_remaining" in columns
    with open(path, newline="") as handle:
        written = list(csv.DictReader(handle))
    assert written[0]["fuel_remaining"] == "" and written[1]["fuel_remaining"] == "12.5"


# --- the statistics ---------------------------------------------------------


def test_the_wilson_interval_matches_the_published_figures():
    low, high = sweep.wilson(50, 100)
    assert low == pytest.approx(0.4038, abs=1e-4)
    assert high == pytest.approx(0.5962, abs=1e-4)


def test_the_interval_of_no_wins_at_all_stays_above_zero_width():
    # the reason for Wilson rather than the normal approximation: 0/100 has to say "at most about 3.7%",
    # not "exactly 0%", or a scan reads an unwinnable arm and a merely hard one as the same thing
    low, high = sweep.wilson(0, 100)
    assert low == 0.0
    assert high == pytest.approx(0.0370, abs=1e-4)


def test_the_interval_never_leaves_the_unit_interval():
    for wins, trials in [(0, 1), (1, 1), (0, 400), (400, 400), (1, 3), (10, 100)]:
        low, high = sweep.wilson(wins, trials)
        assert 0.0 <= low <= high <= 1.0


def test_more_runs_narrow_the_interval():
    narrow = sweep.wilson(40, 400)
    wide = sweep.wilson(4, 40)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_the_summary_counts_wins_against_the_runs_that_had_an_outcome():
    stats = sweep.summarise(fake_results(40, wins=4))
    assert stats["wins"] == 4 and stats["decided"] == 40
    assert stats["rate"] == pytest.approx(0.1)


def test_a_run_with_no_base_to_lose_is_not_counted_as_a_loss():
    # ACTIVATE_FIREFIGHTING off reports N/A, and folding those into the denominator is how a mis-set sweep
    # produces a convincing 0% win rate
    stats = sweep.summarise([{"outcome": "N/A"} for _ in range(10)])
    assert stats["rate"] is None and stats["decided"] == 0 and stats["n"] == 10


def test_errored_runs_are_reported_rather_than_averaged_away():
    rows = fake_results(10, wins=1) + [{"outcome": "LOST", "error": "boom"}]
    assert sweep.summarise(rows)["errors"] == 1


# --- the bisection ----------------------------------------------------------


@pytest.fixture
def synthetic(monkeypatch):
    """Replace the simulator with a known monotone response, so the search can be checked against it.

    The response is linear in the knob and deterministic -- every run of an arm agrees -- which is the
    friendliest thing bisection can be given. A search that cannot find the crossing of a straight line is
    not going to find it in a wildfire.
    """

    def _install(response, runs=100):
        def fake_run_arm(arm, options, out_dir):
            value = next(iter(arm.params.values()))
            wins = round(response(value) * runs)
            return fake_results(runs, wins=wins)

        monkeypatch.setattr(sweep, "run_arm", fake_run_arm)
        monkeypatch.setattr(sweep, "write_csv", lambda path, rows: [])

    return _install


def calibration(**overrides):
    argv = ["calibrate", "--knob", "EXTINGUISH_SCALE", "--low", "0.0", "--high", "1.0",
            "--runs", "100", "--out", "unused"]
    for name, value in overrides.items():
        argv += [f"--{name.replace('_', '-')}", str(value)]
    options = sweep.build_parser().parse_args(argv)
    options.base = {}
    return options


def test_the_bisection_finds_the_value_that_hits_the_target(synthetic):
    synthetic(lambda scale: scale)                      # win rate == the knob
    value, stats = sweep.calibrate(calibration(target=0.10), report=lambda *args: None)
    assert value == pytest.approx(0.10, abs=0.05)
    assert stats["rate"] == pytest.approx(0.10, abs=0.05)


def test_the_direction_is_measured_not_assumed(synthetic):
    # BHP and grid size make a scenario easier as they grow, extinguish strength and spread speed make it
    # harder. A bisection that assumed one direction would converge confidently on the wrong endpoint for
    # half the knobs worth sweeping.
    synthetic(lambda scale: 1.0 - scale)                # win rate falls as the knob rises
    value, _ = sweep.calibrate(calibration(target=0.10), report=lambda *args: None)
    assert value == pytest.approx(0.90, abs=0.05)


def test_a_target_outside_the_bracket_is_reported_rather_than_guessed_at(synthetic):
    synthetic(lambda scale: 0.5 + 0.1 * scale)          # never below 50%
    assert sweep.calibrate(calibration(target=0.10), report=lambda *args: None) is None


def test_the_search_stops_once_the_interval_covers_the_target(synthetic):
    # at 100 runs the interval around 10% is about 6 points wide, so halving past that reads noise. The
    # search must stop there rather than spending its whole budget on it.
    probes = []
    synthetic(lambda scale: probes.append(scale) or scale)
    sweep.calibrate(calibration(target=0.10, max_probes=20), report=lambda *args: None)
    assert len(probes) < 20


def test_the_search_terminates_when_the_bracket_closes(synthetic):
    # a knob with a cliff in it: no value gives 10%, and the bisection has to give up on the tolerance
    # rather than probe forever
    synthetic(lambda scale: 0.0 if scale < 0.5 else 1.0)
    value, stats = sweep.calibrate(calibration(target=0.10, tolerance=0.01), report=lambda *args: None)
    assert value is not None
    assert stats["rate"] in (0.0, 1.0)      # honestly reported as nowhere near the target
