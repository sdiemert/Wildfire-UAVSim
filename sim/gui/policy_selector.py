# python libraries

import json

from mesa.visualization.ModularVisualization import VisualizationElement


# Class PolicySelector moves a model parameter control out of the left hand sidebar and into the strip
# above the grid, on the right hand side of the page. The sidebar is then left to the status panel alone,
# which is where vertical space is scarce.
#
# Mesa builds the parameter controls itself, in initGUI(), and always appends them to the sidebar. That
# happens when the model parameters arrive over the websocket, which is after the element scripts have
# run, so the control cannot simply be picked up on load: the sidebar is watched instead and the control
# is carried over as soon as Mesa creates it, with its change handler intact.
#
# One of these is added per control to be moved, so the strip is shared: the first instance to run builds
# the panel and injects the styles, and the rest find it and append to it. Building it unconditionally
# would give the page two elements with the same id and two competing flex layouts.
class PolicySelector(VisualizationElement):

    package_includes = []

    def __init__(self, param="policy"):
        """Move the control for a single model parameter to the right hand side.

        Args:
            param: name of the parameter, as it is keyed in the dictionary returned by model_params().
                   Mesa gives its input the id "<param>_id", which is what the control is found by.

        Several of these may be used together, one per parameter. They share the strip, and each control
        appears in it in the order Mesa creates it in the sidebar, which is the order model_params()
        lists them.
        """
        self.param = param
        self.js_code = """
            elements.push((function () {
                // the strip is shared between however many controls are being moved, so it is only built
                // once; every instance after the first finds it and appends to it
                let panel = document.getElementById("model-controls");
                if (panel === null) {
                    const style = document.createElement("style");
                    style.innerHTML = `
                        #elements-topbar { display: flex; align-items: center;
                                           justify-content: space-between;
                                           flex-wrap: wrap; gap: 0.75rem; margin-bottom: 0.5rem; }
                        #elements-topbar p { margin: 0; }
                        /* the controls are stacked rather than laid out in a row: the strip shares its
                           line with the run buttons and the step counter, and a row of them pushes the
                           whole bar wider than the grid on a narrow window */
                        #model-controls { display: flex; flex-direction: column; align-items: flex-end;
                                          gap: 0.3rem; margin-left: auto; }
                        #model-controls > div { display: flex; align-items: center; gap: 0.5rem; }
                        #model-controls p { margin: 0; }
                        /* a shared minimum width, so that the dropdowns line up down their right hand
                           edge however long each label happens to be */
                        #model-controls select { width: auto; min-width: 9rem; font-size: 0.85rem;
                                                 padding: 0.15rem 1.75rem 0.15rem 0.5rem; }
                    `;
                    document.head.appendChild(style);

                    panel = document.createElement("div");
                    panel.id = "model-controls";
                    document.getElementById("elements-topbar").appendChild(panel);
                }

                // the control is a div holding the label and the input Mesa built, so moving the parent
                // of the input moves the whole control
                const move = function () {
                    const input = document.getElementById("%s_id");
                    if (!input) {
                        return false;
                    }
                    panel.appendChild(input.parentElement);
                    return true;
                };

                if (!move()) {
                    const sidebar = document.getElementById("sidebar");
                    const observer = new MutationObserver(function () {
                        if (move()) {
                            observer.disconnect();
                        }
                    });
                    observer.observe(sidebar, { childList: true });
                }

                // the control is driven by the browser alone, so there is nothing to draw on a step. The
                // element still takes part in the render cycle to keep the server side elements lined up
                // with the data the page receives.
                return { render: function () {}, reset: function () {} };
            })());
        """ % self.param

    def render(self, model):
        return ""


# Class ControlGate greys out one model parameter control while another one makes it meaningless, and
# holds it at the value that will actually be used in the meantime.
#
# It exists for the UAV policy control. A managing system allocates a policy to each UAV itself, and
# overwrites whatever the run started under within a few steps, so leaving the control live is a promise
# the page cannot keep: you pick `random`, the team flies it briefly, and then the managing system puts
# everyone on something else without the dropdown ever changing to say so. Disabling it whenever a managing
# system is running says what is actually true, and setting it to the policy the team will start under
# keeps what is shown equal to what is used.
class ControlGate(VisualizationElement):

    package_includes = []

    def __init__(self, param, depends_on, enabled_for, disabled_value=None, reason=""):
        """Enable one control only while another holds one of a set of values.

        Args:
            param: the control to gate, keyed as in model_params().
            depends_on: the control whose value decides.
            enabled_for: the values of 'depends_on' that leave 'param' usable.
            disabled_value: what to set 'param' to while it is gated off, so that the page shows the
                            value that will really be used rather than a stale one. None leaves it alone.
            reason: tooltip explaining why it is greyed out.
        """
        self.param = param
        self.js_code = """
            elements.push((function () {
                const enabledFor = %(enabled_for)s;
                const disabledValue = %(disabled_value)s;

                // Mesa builds its dropdowns with the *index* as each option's value and maps it back
                // through its own choices array: `<option value=2>remote</option>`, and
                // `onchange = () => submit(param, obj.choices[select.value])`. So select.value is "2",
                // never "remote", and everything here has to work in labels and go through the option
                // list. Comparing select.value against a choice name silently never matches, and
                // assigning a choice name to select.value silently deselects the control -- which then
                // submits obj.choices[""] === undefined, and the server raises KeyError: 'value'.
                const labelOf = function (select) {
                    return select.selectedIndex >= 0
                        ? select.options[select.selectedIndex].text.trim()
                        : null;
                };

                // selects the option with the given label, announcing the change the way a user would.
                // Does nothing if that label is not among the options, so a mismatch cannot deselect it.
                const selectLabel = function (select, label) {
                    for (let index = 0; index < select.options.length; index++) {
                        if (select.options[index].text.trim() === label) {
                            if (select.selectedIndex !== index) {
                                select.selectedIndex = index;
                                select.dispatchEvent(new Event("change"));
                            }
                            return true;
                        }
                    }
                    return false;
                };

                const attach = function () {
                    const driver = document.getElementById("%(depends_on)s_id");
                    const target = document.getElementById("%(param)s_id");
                    if (!driver || !target) {
                        return false;
                    }

                    const apply = function () {
                        const usable = enabledFor.indexOf(labelOf(driver)) !== -1;
                        // the value is set before the control is disabled, and the change announced, so
                        // that the server records the value the page is showing
                        if (!usable && disabledValue !== null) {
                            selectLabel(target, disabledValue);
                        }
                        target.disabled = !usable;
                        target.title = usable ? "" : "%(reason)s";
                        const control = target.parentElement;
                        if (control) {
                            control.style.opacity = usable ? "" : "0.45";
                        }
                    };

                    driver.addEventListener("change", apply);
                    apply();
                    return true;
                };

                // both controls are built by Mesa when the model parameters arrive over the websocket,
                // which is after this script runs, so the sidebar is watched until they exist
                if (!attach()) {
                    const sidebar = document.getElementById("sidebar");
                    const observer = new MutationObserver(function () {
                        if (attach()) {
                            observer.disconnect();
                        }
                    });
                    observer.observe(sidebar, { childList: true });
                }

                return { render: function () {}, reset: function () {} };
            })());
        """ % {
            "param": param,
            "depends_on": depends_on,
            "enabled_for": json.dumps(list(enabled_for)),
            "disabled_value": json.dumps(disabled_value),
            "reason": reason.replace('"', "'"),
        }

    def render(self, model):
        return ""
