# python libraries

from mesa.visualization.ModularVisualization import VisualizationElement


# Class FpsTopbar moves the "Frames Per Second" control from the strip above the grid into the top bar,
# next to the Start / Step / Reset buttons it belongs with.
#
# Mesa builds that control into its own page template, which lives inside the installed package and cannot
# be edited from here, so the element is moved on the client instead. Element scripts run after
# runcontrol.js, which is what turns the plain input into a slider, so by the time this code runs the whole
# control is built and can be carried over to the navbar with its handlers intact.
class FpsTopbar(VisualizationElement):

    package_includes = []

    js_code = """
        elements.push((function () {
            // the label is the only node with a stable id: bootstrap-slider copies "fps" onto the slider it
            // builds, so getElementById("fps") no longer returns the input. Its parent is the small block
            // holding the label, the slider and the now hidden input, and moving it moves all three.
            const control = document.querySelector('label[for="fps"]').parentElement;
            const label = control.querySelector('label');
            label.style.marginRight = "";  // the template spaces the label with an inline margin
            // the slider reserves room underneath itself for its tick labels, which are hidden below
            control.querySelector('.slider').style.marginBottom = "";

            // the slider ticks are hidden to keep the bar to one line, so the value is shown as a number
            const value = document.createElement("span");
            value.className = "fps-value";
            value.innerText = fpsControl.getValue();
            fpsControl.on("change", () => { value.innerText = fpsControl.getValue(); });
            control.appendChild(value);

            const style = document.createElement("style");
            style.innerHTML = `
                #fps-control { display: flex; align-items: center; gap: 0.5rem; margin-right: 1.5rem; }
                #fps-control > div { display: flex; align-items: center; gap: 0.5rem; }
                #fps-control .slider.slider-horizontal { width: 140px; }
                #fps-control .slider-tick-label-container { display: none; }
                #fps-control .fps-value { color: #f8f9fa; font-variant-numeric: tabular-nums;
                                          min-width: 1.5rem; margin-left: 0.25rem; }
            `;
            document.head.appendChild(style);

            const item = document.createElement("li");
            item.id = "fps-control";
            item.className = "nav-item";
            item.appendChild(control);

            // the list on the right hand side of the top bar, ahead of the Start button
            const controls = document.getElementById("play-pause").parentElement;
            controls.insertBefore(item, controls.firstChild);

            // the control is driven by the browser alone, so there is nothing to draw on a step. The
            // element still takes part in the render cycle to keep the server side elements lined up
            // with the data the page receives.
            return { render: function () {}, reset: function () {} };
        })());
    """

    def render(self, model):
        return ""
