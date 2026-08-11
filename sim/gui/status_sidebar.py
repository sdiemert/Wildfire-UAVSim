# python libraries

from html import escape

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
             keeps a margin clear of it rather than letting its values disappear underneath.
             The sidebar is a bootstrap col-4, about 23rem on a wide window, and the panel used to cap
             itself well inside that and crowd its own text for no reason. */
          #status-sidebar { font-size: 0.75rem; line-height: 1.2; margin-bottom: 0.5rem;
                            max-width: min(23rem, 100%); padding-right: 1rem; }
          #status-sidebar h4 { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.06em;
                               color: #6c757d; font-weight: 600; margin: 0.5rem 0 0.15rem;
                               border-bottom: 1px solid #e9ecef; padding-bottom: 0.1rem; }
          #status-sidebar h4:first-of-type { margin-top: 0; }
          #status-sidebar h4 .count { float: right; text-transform: none; letter-spacing: 0; }
          /* facts are paired up two to a line, so a section costs half the height it used to */
          #status-sidebar .grid { display: grid; grid-template-columns: 1fr 1fr; column-gap: 0.6rem; }
          /* one fact to a line, for a value that is a name rather than a number: half a line is about
             twenty characters, and "defensive (local)" does not fit in it */
          #status-sidebar .grid.wide { grid-template-columns: 1fr; }
          #status-sidebar .cell { display: flex; justify-content: space-between; align-items: baseline;
                                  gap: 0.3rem; padding: 0.05rem 0; min-width: 0; }
          #status-sidebar .name { color: #495057; white-space: nowrap; overflow: hidden;
                                  text-overflow: ellipsis; }
          /* a value that outgrows its half of the line is cut with an ellipsis rather than spilling into
             the cell beside it, which is what a long one used to do: .name has always been cut this way
             and .value was not, so the wide half of the pair was the one that overflowed */
          #status-sidebar .value { font-variant-numeric: tabular-nums; font-weight: 600; color: #212529;
                                   white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                                   min-width: 0; }
          /* separates the groups within a section: what is running, what it decided, and why */
          #status-sidebar .rule { border-top: 1px solid #f1f3f5; margin: 0.3rem 0 0.2rem; }
          /* the allocation, as one bar of the whole team rather than a list of counts. It is the thing
             that changes every step, so it is worth reading as a shape. */
          #status-sidebar .bar { display: flex; height: 0.45rem; border-radius: 999px; overflow: hidden;
                                 background: #e9ecef; margin: 0.15rem 0 0.2rem; }
          #status-sidebar .bar span { display: block; height: 100%; }
          #status-sidebar .legend { display: flex; flex-wrap: wrap; gap: 0 0.6rem; }
          #status-sidebar .legend .item { display: flex; align-items: baseline; gap: 0.25rem;
                                          white-space: nowrap; }
          #status-sidebar .dot { width: 0.45rem; height: 0.45rem; border-radius: 2px; flex: none;
                                 align-self: center; }
          /* the planner's account of itself: the most informative line in the panel, and the one that was
             hardest to read. Given a quote's shape, and held to two lines with the whole of it on hover,
             so that a long rationale cannot push the team off the bottom of the column. */
          #status-sidebar .quote { border-left: 2px solid #dee2e6; padding-left: 0.4rem; margin: 0.1rem 0;
                                   color: #495057; display: -webkit-box; -webkit-line-clamp: 2;
                                   line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
          /* the policy a UAV is flying, in the colour it is drawn on the map. flex:none keeps it whole:
             it shares its line with .who, which is the span that gives way when the column is narrow. */
          #status-sidebar .unit .tag { flex: none; font-weight: 600; }
          /* where a UAV believes it is, shown only under the positioning error extension. flex:none for the
             same reason as .tag, and greyed when the fix happens to be exact so that a line worth reading
             is the one that stands out. */
          #status-sidebar .unit .fix { flex: none; font-variant-numeric: tabular-nums; }
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

    # one cell to a line, for a value too long to live in half of one
    def wide(self, cells):
        return f'<div class="grid wide">{"".join(cells)}</div>'

    def rule(self):
        return '<div class="rule"></div>'

    # a proportional bar of the team, one segment per policy, in the colours the UAVs are drawn in.
    # 'counts' is {policy name: how many UAVs}, most common first.
    def bar(self, counts):
        total = sum(counts.values())
        if not total:
            return ""

        segments = "".join(
            f'<span style="width:{100.0 * count / total:.1f}%;background:{self.policy_color(name)}"'
            f' title="{name}: {count}"></span>'
            for name, count in counts.items()
        )
        legend = "".join(
            f'<span class="item"><span class="dot" style="background:{self.policy_color(name)}"></span>'
            f'<span class="name">{name}</span><span class="value">{count}</span></span>'
            for name, count in counts.items()
        )
        return f'<div class="bar">{segments}</div><div class="legend">{legend}</div>'

    # the colour a policy is drawn in, on the map and here. Anything without one of its own gets the plain
    # UAV colour, so a policy added to the simulation costs nothing here until it is worth telling apart.
    def policy_color(self, name):
        return config.POLICY_COLORS.get(name, config.UAV_COLOR)

    # a line of free text the planner wrote, held to two lines with the whole of it on hover.
    #
    # Escaped, unlike the numbers the rest of the panel is built from, because this is the one thing on the
    # page that a *remote* managing system supplies: it arrives as the "rationale" field of a JSON response
    # from a server (see sim/managing/remote.py) and is written into the sidebar with innerHTML. Everything
    # else that server sends is validated against the simulation before it is shown -- a policy name has to
    # be one the simulation has -- but free text cannot be, so it is escaped instead of trusted.
    def quote(self, text):
        safe = escape(str(text), quote=True)
        return f'<div class="quote" title="{safe}">{safe}</div>'

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
        # the wind, when there is one. Left out entirely on a still day rather than shown as "none", the
        # way the base is left out with the firefighting extension off: a panel that reports the settings
        # a run is not using costs a cell of a small grid to say nothing.
        if model.wind.wind_direction is not None:
            cells.append(self.wind_cell(model))
        if config.ACTIVATE_FIREFIGHTING:
            cells.extend(self.base_cells(model))
        return self.heading("Status", f"step {model.evaluation_timesteps_counter}") + self.grid(cells)

    # which way the wind is blowing, and how long it has left before it turns. Worth a cell of its own
    # because a wind drawn from a list is different every run and can change part way through one: without
    # it, a fire front that suddenly swings looks like a bug rather than the weather.
    #
    # The countdown is only shown for a wind that can actually turn. A fixed wind would sit there counting
    # down to a redraw that changes nothing, which reads as an event about to happen.
    def wind_cell(self, model):
        wind = model.wind
        name = wind.wind_direction.replace("_", "-").title()
        if not wind.is_variable():
            return self.cell("Wind", name)
        return self.cell("Wind", f"{name} &middot; {wind.variability - wind.steps_held} step(s)")

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

        html = [self.heading("Managing system", f"{model.adaptations()} adaptations")]

        # which one is running, and where, on a line of its own: it is a name rather than a number, and
        # "defensive (local)" does not fit in the twenty-odd characters half a line gives it.
        #
        # Both ManagingSystem and RemoteManagingSystem carry a 'name' and a 'location', which is what they
        # are guaranteed to have in common; anything reached through one and not the other breaks the panel
        # for whichever kind was not being looked at when it was written.
        # the location is only worth adding when it says something the name did not: the managing system
        # called 'remote' would otherwise be reported as "remote &middot; remote"
        name, location = model.managing.name, model.managing_location
        running = name if name == location else f"{name} &middot; {location}"
        html.append(self.wide([self.cell("Running", running)]))

        # what it is made of, but only the parts that are not the default for their role. A managing system
        # is five interchangeable components and the dropdown gives only its name, so this is worth saying
        # -- but naming all five spent three of this section's six lines to report that three of them were
        # 'default', which is how the panel came to be unreadable. What is left is the part a reader could
        # not have guessed, including a combination --mape produced that no registered name describes.
        # Nothing at all for a remote managing system, whose components are the server's.
        varies = self.composition_worth_showing(model)
        if varies:
            html.append(self.wide([self.cell("Made of", " &middot; ".join(varies))]))

        # trouble, when there is any. Both are silent on a healthy run and both mean the run is being
        # managed less than it was asked to be, so they are worth their own line when they appear.
        trouble = []
        # only a remote managing system has 'failures', hence getattr: a run managed remotely is worth
        # telling apart from one that fell back to the local stand-in because the server was not answering
        failures = getattr(model.managing, "failures", 0)
        if failures:
            trouble.append(self.cell("Fell back", f"{failures}x", "value crit"))
        if model.effector is not None and model.effector.rejected:
            trouble.append(self.cell("Refused", model.effector.rejected, "value crit"))
        if trouble:
            html.append(self.grid(trouble))

        # what the team is flying right now, as one bar of the whole team in the colours the UAVs are drawn
        # in on the map, most common first. One line whatever the allocation is, where a list of counts
        # grew a line for every two policies -- and it reads as a shape, which is what the allocation is.
        if counts:
            html.append(self.rule())
            html.append(self.bar(dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))))

        # the planner's own account of why, which is what makes the allocation above readable
        rationale = model.rationale()
        if rationale:
            html.append(self.rule())
            html.append(self.quote(rationale))
        return "".join(html)

    # the components of the running managing system that are not simply the default for their role, as
    # "cautious &middot; defensive" -- the part of its composition a reader could not have guessed.
    #
    # A system whose five components are all the defaults says nothing here, because its name already did.
    def composition_worth_showing(self, model):
        from sim.managing import REGISTRIES

        return [name for role, name in model.composition().items()
                if role in REGISTRIES and name != REGISTRIES[role].default]

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
    #
    # With the positioning error extension on, each line carries two positions: where the UAV really is,
    # and after the "~" where it believes it is, which is the position its policy is planning from and the
    # one it reports to the rest of the team. Seeing the pair side by side is the point -- the gap between
    # them is the whole of what the extension does, and a run where a UAV sits on the base while insisting
    # it is three cells away is otherwise very hard to account for.
    #
    # Asking a UAV where it thinks it is takes nothing from SYSTEM_RANDOM -- formulas.position_noise() works
    # the fix out from the UAV and the step number instead -- so rendering the panel cannot change the run it
    # is showing. That is a property worth not losing: a panel that had to draw would mean a simulation
    # watched in the browser came out differently from the same one in headless.py, and it would be found by
    # somebody comparing results rather than by a test. tests/gui/test_status_sidebar.py runs a watched
    # simulation against an unwatched one to keep it honest.
    def uavs(self, model):
        crew = model.uavs
        flying = sum(1 for uav in crew if uav.is_alive())
        counted = f"{flying}/{len(crew)} flying"
        if config.ACTIVATE_POSITION_ERROR:
            counted += " &middot; is ~ thinks"
        html = [self.heading("UAVs", counted)]
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
                # the policy this UAV is flying is shown next to where it is, so that what it is doing can
                # be read against what it was told to do, and in the colour it is drawn in on the map, so
                # that the line and the marker are found by the same thing.
                #
                # It is a span of its own rather than part of .who: .who is the span that gives way when
                # the column is narrow, so a policy inside it was the first thing to be cut -- which is the
                # newest and most interesting field on the line.
                allocated = allocation.get(uav.unique_id, "")
                html.append(f'<span class="who">{index} {uav.pos}</span>')
                # where it believes it is, next to where it is. Greyed when the two agree, so that scanning
                # the column shows which UAVs are currently lost rather than which ones happen to be listed.
                if config.ACTIVATE_POSITION_ERROR:
                    fix = uav.measured_pos()
                    exact = fix == uav.pos
                    html.append(f'<span class="fix{" muted" if exact else " warn"}">'
                                f'~{fix}</span>')
                if allocated:
                    html.append(f'<span class="tag" style="color:{self.policy_color(allocated)}">'
                                f'{allocated}</span>')
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
