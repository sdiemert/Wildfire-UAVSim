# python libraries

import json

from mesa.visualization.ModularVisualization import VisualizationElement


# Class TopBar rebuilds the strip along the top of the page so that everything used to drive a run sits
# together in it: the frames per second slider, the step the run has reached, and the Start / Step / Reset
# buttons, each with an icon.
#
# Mesa builds that bar into its own page template, which lives inside the installed package and cannot be
# edited from here, so the bar is rearranged on the client instead. Element scripts run after
# runcontrol.js, which is what turns the plain input into a slider and what wires the buttons up, so by the
# time this code runs everything is built and can be moved with its handlers intact.
#
# Two things about runcontrol.js constrain what may be done here:
#   * it holds a reference to the "currentStep" span, so that span is moved rather than replaced;
#   * it writes the button label with "play-pause".firstElementChild.innerText, which wipes out anything
#     nested inside the anchor. The icons are therefore siblings of the anchor, ordered ahead of it with
#     CSS, and the anchor stays the first element child of its list item. The click handler is bound to the
#     list item, so the icons are part of the button as far as a click is concerned.
class TopBar(VisualizationElement):

    package_includes = []

    # the icons, as inline SVG so that the page keeps to the assets Mesa already serves. "reset" is drawn
    # as a skip to start rather than as a circular arrow, which reads as "back to step 0" beside the skip
    # forward of "step".
    ICONS = {
        "play": '<path d="M4.5 3.2v9.6l8-4.8z"/>',
        "stop": '<rect x="4" y="4" width="8" height="8" rx="1.2"/>',
        "done": '<path d="M6.5 11.9 3.1 8.5l1.2-1.2 2.2 2.2 5.2-5.2 1.2 1.2z"/>',
        "step": '<path d="M3.8 3.2v9.6l7-4.8z"/><rect x="11" y="3.2" width="1.8" height="9.6" rx="0.6"/>',
        "reset": '<rect x="3.2" y="3.2" width="1.8" height="9.6" rx="0.6"/><path d="M12.8 3.2v9.6L5.8 8z"/>',
    }

    js_code = """
        elements.push((function () {
            const icons = __ICONS__;

            const style = document.createElement("style");
            style.innerHTML = `
                #sim-controls { display: flex; align-items: center; gap: 0.1rem; }
                #sim-controls > li { display: flex; align-items: center; padding-top: 0.3rem;
                                     padding-bottom: 0.3rem; }
                /* the readout sits right beside the buttons, so it is boxed to make plain that it is
                   something to read rather than something to press, and the box is what separates the
                   speed slider from the buttons */
                #step-counter { border: 1px solid rgba(255, 255, 255, 0.28); border-radius: 0.35rem;
                                padding: 0.15rem 0.6rem; margin: 0 0.7rem 0 1.1rem; }
                #step-counter .label { text-transform: uppercase; font-size: 0.7rem;
                                       letter-spacing: 0.07em; color: #adb5bd; margin-right: 0.5rem; }
                #step-counter #currentStep { color: #f8f9fa; font-weight: 600; font-size: 1rem;
                                             font-variant-numeric: tabular-nums; min-width: 2.2ch;
                                             display: inline-block; text-align: right; }

                #fps-control > div { display: flex; align-items: center; gap: 0.75rem; }
                #fps-control .slider.slider-horizontal { width: 170px; }
                /* the ticks at either end of the track are shown as dots and labels, which crowd a
                   slider this short; the value beside it says where the handle is instead */
                #fps-control .slider-tick-label-container, #fps-control .slider-tick { display: none; }
                #fps-control label { margin: 0; font-size: 0.7rem; letter-spacing: 0.07em; }
                #fps-control .fps-value { color: #f8f9fa; font-variant-numeric: tabular-nums;
                                          font-weight: 600; min-width: 2.2ch; text-align: right; }

                /* the click handler lives on the list item, so the whole button, icon included, is hot */
                #sim-controls .ctl { cursor: pointer; border-radius: 0.35rem; padding: 0.1rem 0.6rem;
                                     gap: 0.4rem; }
                #sim-controls .ctl:hover { background: rgba(255, 255, 255, 0.12); }
                #sim-controls .ctl .nav-link { padding: 0.25rem 0; }
                #sim-controls .ctl .icon { order: -1; display: flex; color: #adb5bd; }
                #sim-controls .ctl:hover .icon { color: #f8f9fa; }
            `;
            document.head.appendChild(style);

            // the list on the right hand side of the top bar, which already holds the buttons
            const controls = document.getElementById("play-pause").parentElement;
            controls.id = "sim-controls";

            // the step the run has reached, moved up from the strip above the grid and parked directly
            // beside the buttons that advance it. The span itself is carried over, because
            // runcontrol.js writes the count straight into it.
            const stepValue = document.getElementById("currentStep");
            const stepReadout = stepValue.parentElement;
            const counter = document.createElement("li");
            counter.id = "step-counter";
            counter.className = "nav-item";
            const label = document.createElement("span");
            label.className = "label";
            label.innerText = "Step";
            counter.appendChild(label);
            counter.appendChild(stepValue);
            stepReadout.remove();
            controls.insertBefore(counter, document.getElementById("play-pause"));

            // the frames per second slider. The label is the only node with a stable id: bootstrap-slider
            // copies "fps" onto the slider it builds, so getElementById("fps") no longer returns the
            // input. Its parent is the small block holding the label, the slider and the now hidden
            // input, and moving it moves all three.
            const fps = document.querySelector('label[for="fps"]').parentElement;
            const fpsLabel = fps.querySelector("label");
            // "Frames Per Second" spelled out crowds the slider, so the bar carries the short form and
            // explains itself on hover
            fpsLabel.innerText = "FPS";
            fpsLabel.title = "Frames per second: how fast the simulation runs";
            fpsLabel.style.marginRight = "";  // the template spaces the label with an inline margin
            // the slider reserves room underneath itself for its tick labels, which are hidden above
            fps.querySelector(".slider").style.marginBottom = "";

            // the ticks are hidden to keep the bar to one line, so the value is shown as a number
            const value = document.createElement("span");
            value.className = "fps-value";
            value.innerText = fpsControl.getValue();
            fpsControl.on("change", () => { value.innerText = fpsControl.getValue(); });
            fps.appendChild(value);

            const fpsItem = document.createElement("li");
            fpsItem.id = "fps-control";
            fpsItem.className = "nav-item";
            fpsItem.appendChild(fps);
            controls.insertBefore(fpsItem, controls.firstChild);

            // gives a button its icon, as a sibling of the anchor that CSS orders ahead of it
            const decorate = function (id, name) {
                const item = document.getElementById(id);
                item.classList.add("ctl");
                const icon = document.createElement("span");
                icon.className = "icon";
                icon.innerHTML = `<svg width="15" height="15" viewBox="0 0 16 16"
                                       fill="currentColor" aria-hidden="true">${icons[name]}</svg>`;
                item.appendChild(icon);
                return icon;
            };

            const playIcon = decorate("play-pause", "play");
            decorate("step", "step");
            decorate("reset", "reset");

            // Start / Stop / Done is a label runcontrol.js rewrites as the run goes on, and it is the only
            // sign of which state the run is in, so the icon follows it
            const anchor = document.getElementById("play-pause").firstElementChild;
            const states = { Start: "play", Stop: "stop", Done: "done" };
            const syncIcon = function () {
                const name = states[anchor.innerText.trim()];
                if (name) {
                    playIcon.firstElementChild.innerHTML = icons[name];
                }
            };
            new MutationObserver(syncIcon).observe(anchor, {
                childList: true, characterData: true, subtree: true
            });

            // the bar is driven by the browser alone, so there is nothing to draw on a step. The element
            // still takes part in the render cycle to keep the server side elements lined up with the
            // data the page receives.
            return { render: function () {}, reset: function () {} };
        })());
    """.replace("__ICONS__", json.dumps(ICONS))

    def render(self, model):
        return ""
