"""What a policy asks a single UAV to do at one time step: a direction and a speed."""

# python libraries

from dataclasses import dataclass

# own python modules

from config import (ACTION_DOWN, ACTION_DUMP_WATER, ACTION_LEFT, ACTION_RIGHT, ACTION_STAY, ACTION_UP)


# names of the movement directions, for readable logs
DIRECTION_NAMES = {
    ACTION_RIGHT: "right",
    ACTION_DOWN: "down",
    ACTION_LEFT: "left",
    ACTION_UP: "up",
    ACTION_STAY: "stay",
    ACTION_DUMP_WATER: "dump water",
}


@dataclass(frozen=True)
class Action:
    """One UAV's order for the next time step.

    'direction' is one of the action constants in config.py, and 'speed' is how many cells the UAV should
    cover along it. The UAV never flies further than UAV_SPEED, whatever a policy asks for, and stops early
    at the edge of the grid or in front of another UAV, so a speed is a request rather than a guarantee.

    Speed is meaningless for the actions that do not move the UAV, and is zero for both of them.
    """

    direction: int
    speed: int = 1

    # holds position for this step
    @classmethod
    def stay(cls):
        return cls(ACTION_STAY, 0)

    # dumps a load of water, which takes the whole step (firefighting extension)
    @classmethod
    def dump(cls):
        return cls(ACTION_DUMP_WATER, 0)

    # accepts what a policy returned and turns it into an Action, so that a policy written before speeds
    # existed keeps working: a bare direction means one cell, as it always did
    @classmethod
    def coerce(cls, value):
        if isinstance(value, cls):
            return value
        if isinstance(value, (tuple, list)):
            if len(value) != 2:
                raise ValueError(f"an action must be a (direction, speed) pair, got {value!r}")
            return cls(int(value[0]), int(value[1]))
        direction = int(value)
        return cls(direction, 0 if direction in (ACTION_STAY, ACTION_DUMP_WATER) else 1)

    # whether this action asks the UAV to fly somewhere
    def is_movement(self):
        return self.direction not in (ACTION_STAY, ACTION_DUMP_WATER) and self.speed > 0

    def __str__(self):
        name = DIRECTION_NAMES.get(self.direction, self.direction)
        if self.direction in (ACTION_STAY, ACTION_DUMP_WATER):
            return str(name)
        return f"{name} at speed {self.speed}"
