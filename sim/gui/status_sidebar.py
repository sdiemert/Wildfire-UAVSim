# python libraries

from mesa.visualization.ModularVisualization import VisualizationElement

# own python modules

# imported as a module rather than with 'from config import *', so that every setting is looked up when it
# is used. A star import copies the values into this module's namespace, which is why a runner overriding a
# constant (see sim/cli/) used to have to reach into every module that had copied it. Reading through
# 'config' leaves one copy to patch, the way the policy package has always done it.
import config


# Class StatusSidebar renders a live status panel in the sidebar of the web page, next to the grid.
#
# Mesa's own TextElement appends its text to the "#elements" column, under the grid. This element pushes a
# panel into the "#sidebar" column instead, which is the one the simulation controls already live in, so
# the status shows up beside the map rather than below it. The panel is inserted before the controls, and
# only its own contents are replaced on each step, leaving the controls untouched.
#
# Vertical space in that column is the scarce resource: the whole run has to be readable without scrolling
# while the map is being watched. So the panel is laid out as a two column grid of label/value pairs, one
# line per fact, and the health of a thing is carried by the colour of its numbers rather than by a bar of
# its own.
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
        if config.ACTIVATE_FIREFIGHTING:
            sections.append(self.out_buildings(model))
        else:
            sections.append(self.note("Firefighting off: see ACTIVATE_FIREFIGHTING in config.py"))
        # the managing system, when there is one. It goes above the team, because what it decided is what
        # the lines below are the consequence of.
        sections.append(self.managing(model))
        # the UAV health points exist whether or not the extension is on, so the team is always reported
        sections.append(self.uavs(model))
        return "".join(sections)

    # the panel is redrawn on every step, so its styles travel with it
    def styles(self):
        return """
        <style>
          /* the grid canvas is positioned absolutely and reaches to the edge of this column, so the panel
             keeps a margin clear of it rather than letting its values disappear underneath */
          #status-sidebar { font-size: 0.75rem; line-height: 1.2; margin-bottom: 0.5rem;
                            max-width: 20rem; padding-right: 1rem; }
          #status-sidebar h4 { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.06em;
                               color: #6c757d; font-weight: 600; margin: 0.5rem 0 0.15rem;
                               border-bottom: 1px solid #e9ecef; padding-bottom: 0.1rem; }
          #status-sidebar h4:first-of-type { margin-top: 0; }
          #status-sidebar h4 .count { float: right; text-transform: none; letter-spacing: 0; }
          /* facts are paired up two to a line, so a section costs half the height it used to */
          #status-sidebar .grid { display: grid; grid-template-columns: 1fr 1fr; column-gap: 0.6rem; }
          #status-sidebar .cell { display: flex; justify-content: space-between; align-items: baseline;
                                  gap: 0.3rem; padding: 0.05rem 0; min-width: 0; }
          #status-sidebar .name { color: #495057; white-space: nowrap; overflow: hidden;
                                  text-overflow: ellipsis; }
          #status-sidebar .value { font-variant-numeric: tabular-nums; font-weight: 600; color: #212529;
                                   white-space: nowrap; }
          /* one line per UAV: index and position, then health, water and score on the right */
          #status-sidebar .unit { display: flex; align-items: baseline; gap: 0.35rem; padding: 0.05rem 0;
                                  white-space: nowrap; }
          #status-sidebar .unit .who { color: #495057; flex: 1 1 auto; overflow: hidden;
                                       text-overflow: ellipsis; }
          #status-sidebar .unit .num { font-variant-numeric: tabular-nums; font-weight: 600; }
          #status-sidebar .ok { color: #2f9e44; }
          #status-sidebar .warn { color: #f08c00; }
          #status-sidebar .muted { color: #868e96; font-style: italic; }
          #status-sidebar .crit { color: #c92a2a; font-weight: 700; }
          #status-sidebar .scroll { max-height: 8rem; overflow-y: auto; }
        </style>
        """

    # a label and its value, one of the two that share a line
    def cell(self, name, value, value_class="value"):
        return f'<div class="cell"><span class="name">{name}</span>' \
               f'<span class="{value_class}">{value}</span></div>'

    # lays cells out two to a line
    def grid(self, cells):
        return f'<div class="grid">{"".join(cells)}</div>'

    # a section heading, with an optional summary parked on the right of the same line
    def heading(self, title, count=None):
        tail = "" if count is None else f'<span class="count">{count}</span>'
        return f"<h4>{title}{tail}</h4>"

    def note(self, text):
        return f'<div class="muted">{text}</div>'

    # class that colours a remaining/total pair green through amber to red as it is used up
    def health_class(self, remaining, total):
        share = 0 if total <= 0 else max(0.0, min(1.0, remaining / total))
        if share > 0.6:
            return "num ok"
        if share > 0.3:
            return "num warn"
        return "num crit"

    # the monitoring metrics, plus the state of the home base, which is a single fact once its health is
    # carried by the colour of the numbers
    def metrics(self, model):
        mr1_total = sum(model.MR1_LIST) if model.MR1_LIST else 0.0
        cells = [self.cell("MR1", f"{mr1_total:.3f}")]
        # MR2 counts how often UAVs flew closer to each other than SECURITY_DISTANCE, which is a risk
        # heuristic; the collisions beside it are the UAVs that actually shared a cell and paid for it
        cells.append(self.cell(f"MR2 &lt;{config.SECURITY_DISTANCE}", model.MR2_VALUE))
        cells.append(self.cell("Collisions", model.collisions,
                               "value crit" if model.collisions else "value"))
        # the ignition can be randomised in config.py, so it is shown here: without it a run that has not
        # caught fire yet looks like a broken simulation
        if model.fire_started:
            cells.append(self.cell("Fire", f"{model.fire_start_pos}"))
        else:
            countdown = model.fire_start_step - model.evaluation_timesteps_counter
            cells.append(self.cell("Fire in", f"{countdown} step(s)", "value muted"))
        if config.ACTIVATE_FIREFIGHTING:
            cells.extend(self.base_cells(model))
        return self.heading("Status", f"step {model.evaluation_timesteps_counter}") + self.grid(cells)

    # the home base, as the two cells it takes up in the metrics grid
    def base_cells(self, model):
        if model.base is None:
            return [self.cell("Base", "none", "value muted")]

        remaining = max(0, config.BHP - model.base.burning_steps)
        cells = [self.cell("Base", f"{remaining} / {config.BHP}", self.health_class(remaining, config.BHP))]
        if model.lost:
            cells.append(self.cell("&nbsp;", "LOST", "value crit"))
        elif model.base.is_burning():
            cells.append(self.cell("&nbsp;", "BURNING", "value crit"))
        else:
            cells.append(self.cell("&nbsp;", "safe", "value ok"))
        return cells

    # the managing system: what it has decided, how often it has changed its mind, and why it last did.
    # Nothing at all when the model is running without one, so the panel is unchanged for a plain run.
    def managing(self, model):
        # the plain WildFireModel has none of these attributes, and neither does the adaptive one with
        # MANAGING_SYSTEM set to 'none'
        if getattr(model, "managing", None) is None:
            return ""

        allocation = model.allocation()
        flying = {uav.unique_id for uav in model.active_uavs()}
        counts = {}
        for uav_id, name in allocation.items():
            if uav_id in flying:
                counts[name] = counts.get(name, 0) + 1

        html = [self.heading("Managing system", f"{model.adaptations()} adaptation(s)")]
        # where it lives. Both ManagingSystem and RemoteManagingSystem carry a 'name', which is the one
        # thing they are guaranteed to have in common; anything reached through one and not the other
        # breaks the panel for whichever kind was not being looked at when it was written.
        cells = [self.cell("Running", model.managing.name)]
        # a run managed remotely is worth telling apart from one that fell back to the local stand-in
        # because the server was not answering: the two produce the same kind of result and mean
        # different things. Only a remote managing system has this, hence getattr.
        failures = getattr(model.managing, "failures", 0)
        if failures:
            cells.append(self.cell("Fell back", f"{failures}x", "value crit"))
        if model.effector is not None and model.effector.rejected:
            cells.append(self.cell("Refused", model.effector.rejected, "value crit"))
        html.append(self.grid(cells))

        # what the team is flying right now, most common first
        if counts:
            html.append(self.grid([
                self.cell(name, count)
                for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            ]))

        # the planner's own account of why, which is what makes the allocation above readable
        rationale = model.rationale()
        if rationale:
            html.append(self.note(rationale))
        return "".join(html)

    # the out buildings. The count in the heading covers the ones that are untouched, so only the buildings
    # that are burning or gone are worth a line of their own.
    def out_buildings(self, model):
        if not model.out_buildings:
            return ""

        standing = len(model.out_buildings) - model.buildings_lost
        html = [self.heading("Out buildings", f"{standing}/{len(model.out_buildings)} standing")]
        damaged = [building for building in model.out_buildings
                   if building.destroyed or building.burning_steps]
        if not damaged:
            return "".join(html + [self.note("all untouched")])

        html.append('<div class="scroll">')
        for building in damaged:
            remaining = max(0, config.OUT_BUILDING_HP - building.burning_steps)
            html.append('<div class="unit">')
            html.append(f'<span class="who">{building.pos}'
                        f'{" &#128293;" if building.is_burning() else ""}</span>')
            if building.destroyed:
                html.append('<span class="num crit">destroyed</span>')
            else:
                html.append(f'<span class="{self.health_class(remaining, config.OUT_BUILDING_HP)}">'
                            f'{remaining}/{config.OUT_BUILDING_HP}</span>')
            html.append("</div>")
        html.append("</div>")
        return "".join(html)

    # the team, one line each: where the UAV is, what health and fuel it has left, whether it is carrying
    # water and what it has scored. The per UAV MR1 lives here rather than in the metrics, which keeps
    # every fact about a UAV on its own line.
    def uavs(self, model):
        crew = model.uavs
        flying = sum(1 for uav in crew if uav.is_alive())
        html = [self.heading("UAVs", f"{flying}/{len(crew)} flying")]
        if not crew:
            return "".join(html + [self.note("none flying")])

        # what each UAV has been allocated, which is empty for a run without a managing system
        allocation = model.allocation() if hasattr(model, "allocation") else {}

        html.append('<div class="scroll">')
        # numbered by their position in the team rather than by unique_id, which starts after every Fire
        # agent has been created. This is the same numbering the MR1 scores use.
        for index, uav in enumerate(crew):
            score = model.MR1_LIST[index] if index < len(model.MR1_LIST) else 0.0
            html.append('<div class="unit">')
            # a destroyed UAV has been taken off the grid, so it has no position left to report
            if not uav.is_alive():
                html.append(f'<span class="who">{index}</span>'
                            f'<span class="num crit">destroyed</span>')
            else:
                # the policy this UAV is flying is shown next to where it is, so that what it is doing
                # can be read against what it was told to do
                allocated = allocation.get(uav.unique_id, "")
                html.append(f'<span class="who">{index} {uav.pos}'
                            f'{f" {allocated}" if allocated else ""}</span>')
                html.append(f'<span class="{self.health_class(uav.hp, config.UAV_HP)}">'
                            f'{uav.hp}/{config.UAV_HP}</span>')
                if config.ACTIVATE_FUEL:
                    # the tank, coloured like the health above, so a UAV running low is as easy to spot
                    # as a damaged one. Shown whole: the fractions it burns are not worth the width.
                    html.append(f'<span class="{self.health_class(uav.fuel, config.UAV_FUEL)}">'
                                f'&#9981;{uav.fuel:.0f}</span>')
                if config.ACTIVATE_FIREFIGHTING:
                    # the water is a load count, so it is shown as a drop that is either lit or greyed out
                    water = f"&#128167;{uav.water}" if uav.has_water() else "&#128167;&ndash;"
                    html.append(f'<span class="num{"" if uav.has_water() else " muted"}">{water}</span>')
            html.append(f'<span class="num">{score:.2f}</span>')
            html.append("</div>")
        html.append("</div>")
        return "".join(html)
