"""Tests for the ControlGate javascript, run against a stub of the DOM Mesa actually builds.

These exist because of a bug that reached the browser and could not have been caught anywhere else in this
suite: the gate compared `select.value` against a choice name. Mesa builds its dropdowns with the *index*
as each option's value and maps it back through its own choices array, so `select.value` is "2" and never
"remote". Two consequences, both of which a user saw:

  * the comparison never matched, so the gated control was disabled permanently -- with the managing
    system set to 'none', no UAV policy could be chosen;
  * assigning a choice name to `select.value` deselected the control, and the change that was then
    announced submitted `obj.choices[""] === undefined`, which reaches the server as a submit_params
    message with no value at all and raises `KeyError: 'value'` in the console.

Nothing in python could have found that, so the javascript is executed here, against a DOM stub that
mimics Mesa's `addChoiceInput()` exactly -- options valued by index, `onchange` mapping back through the
choices array. The stub is the specification; if Mesa changes how it renders a Choice, this is where the
assumption is written down.
"""

# python libraries

import json
import shutil
import subprocess
import textwrap

import pytest

# own python modules

from sim.gui.policy_selector import ControlGate

# the javascript is only worth running if there is something to run it with
node = pytest.mark.skipif(shutil.which("node") is None, reason="node is needed to execute the gate script")


# a DOM stub that renders a Choice the way Mesa's addChoiceInput() does, plus the handful of methods the
# gate uses. Returns whatever the harness printed as JSON.
def run_gate(managing_value, choices=("none", "heuristic", "remote"),
             policy_value="random", policy_choices=("firefighter", "random"),
             disabled_value="firefighter", switch_to=None):
    gate = ControlGate(param="policy", depends_on="managing", enabled_for=["none"],
                       disabled_value=disabled_value, reason="because")

    harness = textwrap.dedent("""
        // --- a stub of Mesa's rendered Choice control -------------------------
        const submitted = [];

        function makeSelect(id, choices, value) {
            const options = choices.map((choice, idx) => ({ text: choice, value: String(idx) }));
            const select = {
                id: id,
                options: options,
                selectedIndex: choices.indexOf(value),
                disabled: false,
                title: "",
                parentElement: { style: {} },
                listeners: [],
                // Mesa's own handler, verbatim in spirit:
                //   select.onchange = () => onSubmitCallback(param, obj.choices[select.value])
                dispatchEvent: function (event) {
                    submitted.push({ param: id, value: choices[Number(this.value)] });
                    this.listeners.forEach((fn) => fn(event));
                },
                addEventListener: function (name, fn) { this.listeners.push(fn); },
            };
            // select.value is the INDEX as a string, exactly as a real <select> behaves
            Object.defineProperty(select, "value", {
                get: function () {
                    return this.selectedIndex >= 0 ? this.options[this.selectedIndex].value : "";
                },
                set: function (v) {
                    const found = this.options.findIndex((o) => o.value === String(v));
                    this.selectedIndex = found;    // -1 when no option matches, as a browser does
                },
            });
            return select;
        }

        const CONTROLS = {
            managing_id: makeSelect("managing_id", MANAGING_CHOICES, MANAGING_VALUE),
            policy_id: makeSelect("policy_id", POLICY_CHOICES, POLICY_VALUE),
        };

        const document = {
            getElementById: function (id) { return CONTROLS[id] || null; },
            head: { appendChild: function () {} },
            createElement: function () { return { style: {}, appendChild: function () {} }; },
        };
        const Event = function (name) { return { type: name }; };
        const MutationObserver = function () { return { observe: function () {}, disconnect: function () {} }; };
        const elements = [];

        // --- the gate under test ---------------------------------------------
        GATE_SCRIPT

        // --- optionally flip the driver, as a user would ----------------------
        if (SWITCH_TO !== null) {
            const driver = CONTROLS.managing_id;
            driver.selectedIndex = MANAGING_CHOICES.indexOf(SWITCH_TO);
            driver.listeners.forEach((fn) => fn({ type: "change" }));
        }

        console.log(JSON.stringify({
            policy_disabled: CONTROLS.policy_id.disabled,
            policy_label: CONTROLS.policy_id.selectedIndex >= 0
                ? CONTROLS.policy_id.options[CONTROLS.policy_id.selectedIndex].text : null,
            policy_selected_index: CONTROLS.policy_id.selectedIndex,
            submitted: submitted,
        }));
    """)

    script = (
        f"const MANAGING_CHOICES = {json.dumps(list(choices))};\n"
        f"const MANAGING_VALUE = {json.dumps(managing_value)};\n"
        f"const POLICY_CHOICES = {json.dumps(list(policy_choices))};\n"
        f"const POLICY_VALUE = {json.dumps(policy_value)};\n"
        f"const SWITCH_TO = {json.dumps(switch_to)};\n"
        + harness.replace("GATE_SCRIPT", gate.js_code)
    )

    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"gate script failed:\n{result.stderr}"
    return json.loads(result.stdout)


# --- the bug that was reported ----------------------------------------------


@node
def test_the_policy_control_is_usable_when_the_managing_system_is_none():
    """The reported bug: with 'none' selected, no policy could be chosen."""
    assert run_gate(managing_value="none")["policy_disabled"] is False


@node
@pytest.mark.parametrize("managing", ["heuristic", "remote"])
def test_the_policy_control_is_locked_while_a_managing_system_runs(managing):
    assert run_gate(managing_value=managing)["policy_disabled"] is True


@node
def test_nothing_undefined_is_ever_submitted():
    """The other half of the bug: a deselected control submitted undefined, and the server raised."""
    for managing in ("none", "heuristic", "remote"):
        result = run_gate(managing_value=managing)
        assert result["policy_selected_index"] >= 0, "the control must never be left deselected"
        for message in result["submitted"]:
            assert message["value"] is not None, f"submitted {message!r} with no value"


# --- what it does while locked ----------------------------------------------


@node
def test_a_locked_control_shows_the_policy_that_will_be_used():
    result = run_gate(managing_value="heuristic", policy_value="random", disabled_value="firefighter")
    assert result["policy_label"] == "firefighter"


@node
def test_the_change_is_announced_so_the_server_agrees_with_the_page():
    result = run_gate(managing_value="heuristic", policy_value="random", disabled_value="firefighter")
    assert {"param": "policy_id", "value": "firefighter"} in result["submitted"]


@node
def test_an_unlocked_control_is_left_on_whatever_was_chosen():
    result = run_gate(managing_value="none", policy_value="random", disabled_value="firefighter")
    assert result["policy_label"] == "random"
    assert result["submitted"] == [], "nothing should be submitted when the control is left alone"


@node
def test_a_default_that_is_not_among_the_options_leaves_the_control_alone():
    # guards the deselection that caused the KeyError: a mismatch must be a no-op, not a wipe
    result = run_gate(managing_value="heuristic", policy_value="random", disabled_value="no-such-policy")
    assert result["policy_selected_index"] >= 0
    assert result["policy_label"] == "random"


# --- reacting to the dropdown live ------------------------------------------


@node
def test_switching_to_none_unlocks_the_policy_control():
    result = run_gate(managing_value="heuristic", switch_to="none")
    assert result["policy_disabled"] is False


@node
def test_switching_away_from_none_locks_it_again():
    result = run_gate(managing_value="none", switch_to="remote")
    assert result["policy_disabled"] is True
    assert result["policy_label"] == "firefighter"


# --- the assumption this all rests on ---------------------------------------


def test_mesa_still_values_its_options_by_index():
    """If this ever stops being true, the gate can be simplified -- and these tests rewritten."""
    import pathlib

    import mesa

    runcontrol = pathlib.Path(mesa.__file__).parent / "visualization" / "templates" / "js" / "runcontrol.js"
    if not runcontrol.exists():
        pytest.skip("mesa's runcontrol.js is not where it used to be")

    source = runcontrol.read_text()
    assert "value=${idx}" in source, "mesa no longer values Choice options by index"
    assert "obj.choices[select.value]" in source, "mesa no longer maps the index back through choices"
