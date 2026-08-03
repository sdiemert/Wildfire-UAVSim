"""The wildfire simulator.

This package holds the simulation itself (the model, the agents and the fire spread), the UAV policies, the
Mesa web interface and the headless command line runner.

The settings are the one thing that is deliberately NOT in here: config.py sits at the repository root,
where anyone opening the project for the first time will see it. Every module reads its settings through
`config.` at the point of use, which is what lets a runner or a test override a constant by setting it on
config alone and have the whole simulation pick it up.
"""
