# python libraries

from mesa.visualization.ModularVisualization import VisualizationElement

# own python modules

import agents

from config import *


# Class StatusSidebar renders a live status panel in the sidebar of the web page, next to the grid.
#
# Mesa's own TextElement appends its text to the "#elements" column, under the grid. This element pushes a
# panel into the "#sidebar" column instead, which is the one the simulation controls already live in, so
# the status shows up beside the map rather than below it. The panel is inserted before the controls, and
# only its own contents are replaced on each step, leaving the controls untouched.
class StatusSidebar(VisualizationElement):

    package_includes = []

    js_code = """
        elements.push((function () {
            const panel = document.createElement("div");
            panel.id = "status-sidebar";
            const sidebar = document.getElementById("sidebar");
            sidebar.insertBefore(panel, sidebar.firstChild);
            return {
                render: function (data) { panel.innerHTML = data; },
                reset: function () { panel.innerHTML = ""; }
            };
        })());
    """

    # builds the whole panel for the current state of the model
    def render(self, model):
        sections = [self.styles(), self.metrics(model)]
        if ACTIVATE_FIREFIGHTING:
            sections.append(self.base(model))
            sections.append(self.out_buildings(model))
        else:
            sections.append(self.note("Firefighting extension off: set ACTIVATE_FIREFIGHTING in config.py "
                                      "to see the base, the out buildings and the UAV water."))
        # the UAV health points exist whether or not the extension is on, so the team is always reported
        sections.append(self.uavs(model))
        return "".join(sections)

    # the panel is redrawn on every step, so its styles travel with it
    def styles(self):
        return """
        <style>
          #status-sidebar { font-size: 0.85rem; line-height: 1.35; margin-bottom: 1rem; }
          #status-sidebar h4 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em;
                               color: #6c757d; margin: 0.9rem 0 0.35rem; font-weight: 600; }
          #status-sidebar .row { display: flex; justify-content: space-between; align-items: baseline;
                                 gap: 0.5rem; padding: 0.1rem 0; }
          #status-sidebar .name { color: #343a40; }
          #status-sidebar .value { font-variant-numeric: tabular-nums; font-weight: 600; color: #212529; }
          #status-sidebar .bar { height: 6px; border-radius: 3px; background: #e9ecef; overflow: hidden;
                                 margin: 0.15rem 0 0.4rem; }
          #status-sidebar .bar span { display: block; height: 100%; }
          #status-sidebar .muted { color: #868e96; font-style: italic; }
          #status-sidebar .alert { color: #c92a2a; font-weight: 700; }
          #status-sidebar .scroll { max-height: 11rem; overflow-y: auto; }
        </style>
        """

    # a line with a label on the left and a value on the right
    def row(self, name, value, value_class="value"):
        return f'<div class="row"><span class="name">{name}</span>' \
               f'<span class="{value_class}">{value}</span></div>'

    # a proportional bar, coloured green through amber to red as the remaining share drops
    def bar(self, remaining, total):
        share = 0 if total <= 0 else max(0.0, min(1.0, remaining / total))
        if share > 0.6:
            color = "#2f9e44"
        elif share > 0.3:
            color = "#f08c00"
        else:
            color = "#c92a2a"
        return f'<div class="bar"><span style="width:{share * 100:.0f}%;background:{color};"></span></div>'

    def note(self, text):
        return f'<div class="muted">{text}</div>'

    # the monitoring metrics, which exist whether or not the extension is on
    def metrics(self, model):
        mr1_total = sum(model.MR1_LIST) if model.MR1_LIST else 0.0
        html = ["<h4>Metrics</h4>"]
        html.append(self.row("MR1 (total)", f"{mr1_total:.3f}"))
        # MR1 is accumulated per UAV, so the individual scores are worth showing when there are several
        if len(model.MR1_LIST) > 1:
            for index, score in enumerate(model.MR1_LIST):
                html.append(self.row(f"&nbsp;&nbsp;UAV {index}", f"{score:.3f}"))
        # MR2 counts how often UAVs flew closer to each other than SECURITY_DISTANCE, which is a risk
        # heuristic; the collisions below are the UAVs that actually shared a cell and paid for it
        html.append(self.row(f"MR2 (within {SECURITY_DISTANCE} cells)", model.MR2_VALUE))
        html.append(self.row("Collisions", model.collisions,
                             "alert" if model.collisions else "value"))
        # the ignition can be randomised in config.py, so it is shown here: without it a run that has not
        # caught fire yet looks like a broken simulation
        if model.fire_started:
            html.append(self.row("Fire at", f"{model.fire_start_pos}"))
        else:
            html.append(self.row("Fire at", f"{model.fire_start_pos} in "
                                            f"{model.fire_start_step - model.evaluation_timesteps_counter} "
                                            f"step(s)", "muted"))
        return "".join(html)

    # the health of the home base
    def base(self, model):
        html = ["<h4>Home base</h4>"]
        if model.base is None:
            return "".join(html + [self.note("no base placed")])

        remaining = max(0, BHP - model.base.burning_steps)
        html.append(self.row("Health", f"{remaining} / {BHP}"))
        html.append(self.bar(remaining, BHP))
        if model.lost:
            html.append(self.row("Status", "DESTROYED &mdash; run lost", "alert"))
        elif model.base.is_burning():
            html.append(self.row("Status", "BURNING", "alert"))
        else:
            html.append(self.row("Status", "safe"))
        return "".join(html)

    # the health of each out building
    def out_buildings(self, model):
        html = [f"<h4>Out buildings ({len(model.out_buildings) - model.buildings_lost}"
                f"/{len(model.out_buildings)} standing)</h4>"]
        if not model.out_buildings:
            return "".join(html + [self.note("none placed")])

        html.append('<div class="scroll">')
        for building in model.out_buildings:
            remaining = max(0, OUT_BUILDING_HP - building.burning_steps)
            if building.destroyed:
                html.append(self.row(f"{building.pos}", "destroyed", "alert"))
            else:
                label = f"{building.pos}" + (" &#128293;" if building.is_burning() else "")
                html.append(self.row(label, f"{remaining} / {OUT_BUILDING_HP}"))
            html.append(self.bar(remaining, OUT_BUILDING_HP))
        html.append("</div>")
        return "".join(html)

    # the health, and with the extension on the water, of each UAV
    def uavs(self, model):
        crew = model.uavs
        flying = sum(1 for uav in crew if uav.is_alive())
        html = [f"<h4>UAVs ({flying}/{len(crew)} flying)</h4>"]
        if not crew:
            return "".join(html + [self.note("none flying")])

        html.append('<div class="scroll">')
        # numbered by their position in the team rather than by unique_id, which starts after every Fire
        # agent has been created. This is the same numbering the MR1 scores above use.
        for index, uav in enumerate(crew):
            # a destroyed UAV has been taken off the grid, so it has no position left to report
            if not uav.is_alive():
                html.append(self.row(f"UAV {index}", "DESTROYED", "alert"))
                html.append(self.bar(0, UAV_HP))
                continue

            html.append(self.row(f"UAV {index} at {uav.pos}", f"{uav.hp} / {UAV_HP} HP"))
            html.append(self.bar(uav.hp, UAV_HP))
            if ACTIVATE_FIREFIGHTING:
                if uav.has_water():
                    html.append(self.row("&nbsp;&nbsp;water", f"{uav.water}/{UAV_WATER_CAPACITY}"))
                else:
                    html.append(self.row("&nbsp;&nbsp;water", "empty", "muted"))
        html.append("</div>")
        return "".join(html)
