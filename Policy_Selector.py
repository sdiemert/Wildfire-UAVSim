# python libraries

from mesa.visualization.ModularVisualization import VisualizationElement


# Class PolicySelector moves a model parameter control out of the left hand sidebar and into the strip
# above the grid, on the right hand side of the page. The sidebar is then left to the status panel alone,
# which is where vertical space is scarce.
#
# Mesa builds the parameter controls itself, in initGUI(), and always appends them to the sidebar. That
# happens when the model parameters arrive over the websocket, which is after the element scripts have
# run, so the control cannot simply be picked up on load: the sidebar is watched instead and the control
# is carried over as soon as Mesa creates it, with its change handler intact.
class PolicySelector(VisualizationElement):

    package_includes = []

    def __init__(self, param="policy"):
        """Move the control for a single model parameter to the right hand side.

        Args:
            param: name of the parameter, as it is keyed in the dictionary returned by model_params().
                   Mesa gives its input the id "<param>_id", which is what the control is found by.
        """
        self.param = param
        self.js_code = """
            elements.push((function () {
                const style = document.createElement("style");
                style.innerHTML = `
                    #elements-topbar { display: flex; align-items: center; justify-content: space-between;
                                       flex-wrap: wrap; gap: 0.75rem; margin-bottom: 0.5rem; }
                    #elements-topbar p { margin: 0; }
                    #model-controls { display: flex; align-items: center; gap: 0.5rem; margin-left: auto; }
                    #model-controls > div { display: flex; align-items: center; gap: 0.5rem; }
                    #model-controls p { margin: 0; }
                    #model-controls select { width: auto; font-size: 0.85rem;
                                             padding: 0.15rem 1.75rem 0.15rem 0.5rem; }
                `;
                document.head.appendChild(style);

                const panel = document.createElement("div");
                panel.id = "model-controls";
                document.getElementById("elements-topbar").appendChild(panel);

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
