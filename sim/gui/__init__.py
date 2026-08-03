"""The Mesa web interface.

  app.py              wires the elements below onto a ModularServer and launches it
  portrayal.py        how each agent is drawn on the grid
  canvas_grid.py      the grid itself, plus the observation window drawn around each UAV
  status_sidebar.py   the live status panel beside the grid
  top_bar.py          the speed slider, the step counter and the run buttons
  policy_selector.py  the UAV policy dropdown above the grid

Mesa is pinned to 1.x for these: 2.0 removed the tornado based ModularServer and ModularVisualization
they are built on. Each element carries its JavaScript inline and pulls its assets from Mesa's own
package_includes, so there are no static files to ship alongside.
"""
