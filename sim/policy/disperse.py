"""Policy that does nothing but open the gap between a UAV and its team mates."""

# own python modules

# see the note in random_policy.py about importing config as a module
import config

from .action import Action
from .base import Policy, avoid, step_towards


class DispersePolicy(Policy):
    """Fly away from the team mates in view until there is room, then hold position.

    Two UAVs that end a step on the same cell collide, and each of them rolls for damage; enough of those
    and the team flies itself to pieces. Every other policy treats that as a constraint on the way to doing
    something else, giving up a cell of speed here and there to stay clear. This one treats it as the whole
    job, and is what the managing system allocates to a UAV that is in trouble: crowded, or down to its last
    health point, or both.

    A UAV under this policy:

      * with nobody in view, or with everyone already SECURITY_DISTANCE away -> holds position
      * otherwise -> flies directly away from the centre of mass of the UAVs it can see, far enough to
        open the gap it is short of, and no further

    It gives up on fighting the fire entirely while it does so, which is the point: the UAV is worth more
    to the run intact and idle than damaged and busy. The managing system is expected to take it off this
    policy once the gap has opened, which is what makes the pairing work.

    The separation aimed for is SECURITY_DISTANCE unless the UAV was allocated one of its own through
    PolicyParams.separation, which is how the managing system asks a badly boxed in UAV for more room than
    the rest of the team keeps.
    """

    name = "disperse"

    def __init__(self):
        # None means "whatever SECURITY_DISTANCE is when the policy runs", so that a run overriding it is
        # picked up. configure() replaces it when a UAV is allocated a separation of its own.
        self.separation = None

    # takes the separation this UAV has been allocated, if it was given one
    def configure(self, params):
        self.separation = None if params is None or not params.separation else int(params.separation)

    # how much clear air this UAV is aiming for
    def target_separation(self):
        return config.SECURITY_DISTANCE if self.separation is None else self.separation

    def select_actions(self, observations):
        return [self.action_for(observation) for observation in observations]

    # decides the action for a single UAV
    def action_for(self, observation):
        neighbours = [tuple(cell) for cell in observation.uav_positions]
        if not neighbours:  # nobody in view, so there is nothing to get away from
            return Action.stay()

        wanted = self.target_separation()
        gap = min(self.distance(observation.pos, neighbour) for neighbour in neighbours)
        if gap >= wanted:  # already far enough from everyone in view
            return Action.stay()

        target = self.escape_target(observation.pos, neighbours, wanted - gap)
        action = step_towards(observation.pos, target)
        # flying onto a cell a team mate holds is the very collision this policy exists to avoid, so the
        # flight is trimmed to stop short of one even when this policy is used on its own. SuperPolicy
        # trims it again against the rest of the fleet.
        return avoid(observation.pos, action, neighbours)

    # the cell this UAV heads for: 'distance' cells directly away from the centre of mass of the UAVs it
    # can see. A UAV sitting exactly on that centre has no direction to run in, and picks one at random
    # rather than holding position in the middle of a crowd.
    def escape_target(self, pos, neighbours, distance):
        centre_x = sum(neighbour[0] for neighbour in neighbours) / len(neighbours)
        centre_y = sum(neighbour[1] for neighbour in neighbours) / len(neighbours)
        away_x = pos[0] - centre_x
        away_y = pos[1] - centre_y

        if away_x == 0 and away_y == 0:
            away_x, away_y = config.SYSTEM_RANDOM.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])

        # scaled so that the longer leg covers the whole gap that is missing, which keeps step_towards()
        # from picking the axis the UAV barely needs to move along
        scale = max(1, int(distance)) / max(abs(away_x), abs(away_y))
        return (round(pos[0] + away_x * scale), round(pos[1] + away_y * scale))

    # how far apart two cells are, counted the way MR2 counts it
    def distance(self, pos, other):
        return ((pos[0] - other[0]) ** 2 + (pos[1] - other[1]) ** 2) ** 0.5
