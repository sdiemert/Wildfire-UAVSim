"""The M of MAPE-K: take a reading and remember it.

Monitor is both the role and the only implementation of it so far, which is why this file is called base.py
and holds a concrete class rather than an abstract one. A monitor that samples, ages or filters readings
would be a sibling of it here, and would be registered alongside it in __init__.py; nothing else would
change, because the loop only ever asks its monitor to observe().
"""


class Monitor:
    """Reads the managed system through a sensor and files the result in the Knowledge base.

    There is deliberately almost nothing here. Everything that could be called monitoring logic -- deciding
    what is worth reporting, and how much of the world a managing system is allowed to see -- lives in the
    sensor, on the managed side, because that is a property of the system being managed rather than of the
    thing managing it. Monitor's job is to say when a reading is taken and where it goes.
    """

    # the name this monitor is registered and selected under
    name = "default"

    # constructor
    def __init__(self, sensor, knowledge, log=None):
        self.sensor = sensor
        self.knowledge = knowledge
        self.log = log

    # takes a reading and records it. Returns the snapshot, which is what the rest of the loop works from.
    def observe(self):
        snapshot = self.sensor.read()
        self.knowledge.record(snapshot)

        # a UAV that has been destroyed is dropped from the hysteresis counters, so that its streak does
        # not sit in the Knowledge base for the rest of the run
        for report in snapshot.uavs:
            if not report.alive:
                self.knowledge.forget(report.uav_id)

        if self.log is not None:
            self.log.debug("monitored step %d: %d UAV(s) flying, %d known fire cell(s)",
                           snapshot.step, len(snapshot.alive()), len(snapshot.known_fire()))
        return snapshot

    def __str__(self):
        return self.name
