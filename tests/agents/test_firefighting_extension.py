"""Tests for the firefighting extension, at the level of the model and its agents.

These build a real WildFireModel on a small grid, because the home base, the refill queue, extinguishing
and re-ignition are all properties of the grid rather than of a policy.
"""

# python libraries

import pytest

# own python modules

from sim import agents
import config

from sim import formulas


# --- helpers ----------------------------------------------------------------


def fire_at(model, position):
    """Returns the Fire agent occupying a cell."""
    for agent in model.grid.get_cell_list_contents([position]):
        if type(agent) is agents.Fire:
            return agent
    return None


def uavs_of(model):
    return [agent for agent in model.schedule.agents if type(agent) is agents.UAV]


# --- the extension is optional ----------------------------------------------


def test_extension_off_places_no_base_and_no_buildings(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=False, NUM_OUT_BUILDINGS=4)
    assert model.base is None
    assert model.out_buildings == []
    assert uavs_of(model)[0].water == 0


def test_extension_on_places_the_base_and_the_buildings(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), NUM_OUT_BUILDINGS=3)
    assert model.base is not None
    assert model.base.pos == (2, 2)
    assert len(model.out_buildings) == 3


# --- the base footprint -----------------------------------------------------


def test_the_base_covers_a_block_of_the_configured_size(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2),
                       NUM_AGENTS=0, NUM_OUT_BUILDINGS=0)
    assert set(model.base.cells) == {(2, 2), (3, 2), (2, 3), (3, 3)}
    # the anchor stays the cell the agent itself sits on
    assert model.base.cells[0] == model.base.pos == (2, 2)
    for cell in model.base.cells:
        assert model.base.covers(cell)
    assert not model.base.covers((4, 4))


def test_every_footprint_cell_is_drawn(make_model):
    # the anchor holds the Base agent, the rest hold a tile each, so the whole block appears on the map
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2),
                       NUM_AGENTS=0, NUM_OUT_BUILDINGS=0)
    drawn = []
    for cell in model.base.cells:
        for agent in model.grid.get_cell_list_contents([cell]):
            if type(agent) in (agents.Base, agents.BaseTile):
                drawn.append(cell)
    assert sorted(drawn) == sorted(model.base.cells)


def test_the_footprint_is_clipped_to_the_grid(make_model):
    # anchored in the far corner, so most of the block would fall outside the grid
    model = make_model(ACTIVATE_FIREFIGHTING=True, WIDTH=9, HEIGHT=9, BASE_POSITION=(8, 8),
                       BASE_SIZE=(2, 2), NUM_AGENTS=0, NUM_OUT_BUILDINGS=0)
    assert model.base.cells == [(8, 8)]


def test_a_base_of_a_different_size_is_honoured(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(1, 1), BASE_SIZE=(3, 2),
                       NUM_AGENTS=0, NUM_OUT_BUILDINGS=0)
    assert len(model.base.cells) == 6
    assert set(model.base.cells) == {(1, 1), (2, 1), (3, 1), (1, 2), (2, 2), (3, 2)}


def test_the_base_burns_when_any_footprint_cell_burns(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), BASE_SIZE=(2, 2),
                       NUM_AGENTS=0, NUM_OUT_BUILDINGS=0)
    assert not model.base.is_burning()

    # a cell of the footprint that is not the anchor
    fire_at(model, (3, 3)).burning = True
    assert model.base.is_burning()


def test_a_uav_refills_anywhere_on_the_footprint(make_model):
    # fuel off, so that the visit lasts BASE_REFILL_STEPS: with the extension on a visit takes
    # max(BASE_REFILL_STEPS, BASE_REFUEL_STEPS), and water and fuel are taken on together
    model = make_model(ACTIVATE_FIREFIGHTING=True, ACTIVATE_FUEL=False, BASE_POSITION=(2, 2),
                       BASE_SIZE=(2, 2), NUM_AGENTS=1, NUM_OUT_BUILDINGS=0, BASE_REFILL_STEPS=1)
    uav = uavs_of(model)[0]
    uav.water = 0
    model.grid.move_agent(uav, (3, 3))  # a corner of the base, not the anchor

    assert model.base.serve(uav) is True
    assert uav.has_water()


def test_uavs_start_at_the_base_with_a_full_load(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), NUM_AGENTS=3,
                       NUM_OUT_BUILDINGS=0)
    for uav in uavs_of(model):
        # a cell of the footprint each rather than all on the anchor, so that the team is not launched
        # stacked; which cell is which is pinned in tests/test_uav_collisions.py
        assert model.base.covers(uav.pos)
        assert uav.has_water()


def test_out_buildings_are_never_placed_on_the_base(make_model):
    # the whole 4x4 grid is offered as a candidate, so a clash would be likely without the guard
    model = make_model(ACTIVATE_FIREFIGHTING=True, WIDTH=4, HEIGHT=4, BASE_POSITION=(1, 1),
                       BASE_SIZE=(2, 2), NUM_OUT_BUILDINGS=15, NUM_AGENTS=0)
    occupied = [building.pos for building in model.out_buildings]
    for cell in model.base.cells:
        assert cell not in occupied
    # more buildings than free cells were requested, so only what fits is placed: 16 cells minus the 4
    # taken by the base footprint
    assert len(model.out_buildings) == 12


# --- dumping water ----------------------------------------------------------


def test_dumping_water_extinguishes_the_cell_underneath(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(4, 4), NUM_AGENTS=1,
                       NUM_OUT_BUILDINGS=0, WATER_EXTINGUISH_PROB_CENTRE=1.0,
                       WATER_EXTINGUISH_PROB_EDGE=1.0, WATER_DROP_RADIUS=0)
    uav = uavs_of(model)[0]
    cell = fire_at(model, uav.pos)
    cell.burning = True

    assert uav.dump_water() == 1
    assert not cell.is_burning()
    assert cell.is_immune()
    assert not uav.has_water()


def test_dumping_water_reaches_the_configured_radius(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(4, 4), NUM_AGENTS=1,
                       NUM_OUT_BUILDINGS=0, WATER_EXTINGUISH_PROB_CENTRE=1.0,
                       WATER_EXTINGUISH_PROB_EDGE=1.0, WATER_DROP_RADIUS=2)
    uav = uavs_of(model)[0]
    for cell in model.grid.get_neighborhood(uav.pos, moore=True, include_center=True, radius=3):
        fire_at(model, cell).burning = True

    uav.dump_water()

    # the drop covers a disc, not the square Moore neighbourhood: a cell is only reached when its Euclidean
    # distance is within WATER_DROP_RADIUS, so the corners of the square are left burning
    for cell in model.grid.get_neighborhood(uav.pos, moore=True, include_center=True, radius=3):
        distance = formulas.euclidean_distance(uav.pos[0], uav.pos[1], cell[0], cell[1])
        within_radius = distance <= config.WATER_DROP_RADIUS
        assert fire_at(model, cell).is_burning() is not within_radius, (cell, distance)


def test_an_empty_uav_cannot_dump(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(4, 4), NUM_AGENTS=1,
                       NUM_OUT_BUILDINGS=0, WATER_EXTINGUISH_PROB_CENTRE=1.0)
    uav = uavs_of(model)[0]
    uav.water = 0
    fire_at(model, uav.pos).burning = True

    assert uav.dump_water() == 0
    assert fire_at(model, uav.pos).is_burning()


def test_dump_probability_falls_off_with_distance():
    config_centre = formulas.extinguish_probability((5, 5), (5, 5))
    edge = formulas.extinguish_probability((5, 5), (5, 5 + config.WATER_DROP_RADIUS))
    beyond = formulas.extinguish_probability((5, 5), (5, 5 + config.WATER_DROP_RADIUS + 1))

    assert config_centre == pytest.approx(config.WATER_EXTINGUISH_PROB_CENTRE)
    assert edge == pytest.approx(config.WATER_EXTINGUISH_PROB_EDGE)
    assert beyond == 0.0
    assert config_centre > edge > beyond


# --- re-ignition ------------------------------------------------------------


def test_an_extinguished_cell_is_immune_for_the_configured_delay(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, NUM_AGENTS=0, NUM_OUT_BUILDINGS=0,
                       BASE_POSITION=(1, 1), REIGNITION_DELAY=3, FIRE_SPREAD_SPEED=1,
                       SPONTANEOUS_REIGNITION_PROB=0.0)
    cell = fire_at(model, (4, 4))
    # surround it with fire, so that it would certainly relight if it were not immune
    for neighbour in model.grid.get_neighborhood((4, 4), moore=True, include_center=False, radius=1):
        fire_at(model, neighbour).burning = True
    cell.extinguish()

    for _ in range(3):
        model.step()
        assert not cell.is_burning()

    # once the delay has passed the neighbouring fire can light it again
    model.step()
    model.step()
    assert cell.is_burning()


def test_an_extinguished_cell_can_relight_spontaneously(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, NUM_AGENTS=0, NUM_OUT_BUILDINGS=0,
                       BASE_POSITION=(1, 1), REIGNITION_DELAY=1, FIRE_SPREAD_SPEED=1,
                       SPONTANEOUS_REIGNITION_PROB=1.0)
    # put the initial fire out first, so that nothing on the grid is burning and the cell below can only
    # catch fire on its own rather than from a neighbour
    fire_at(model, (4, 4)).extinguish()
    cell = fire_at(model, (8, 8))  # far corner, out of reach of the influence radius of the centre
    cell.extinguish()

    model.step()  # burns the immunity off
    model.step()  # relights on its own
    assert cell.is_burning()


def test_a_cell_that_was_never_extinguished_does_not_relight_spontaneously(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, NUM_AGENTS=0, NUM_OUT_BUILDINGS=0,
                       BASE_POSITION=(1, 1), FIRE_SPREAD_SPEED=1, SPONTANEOUS_REIGNITION_PROB=1.0,
                       REIGNITION_DELAY=100)
    # the initial fire is put out and kept out, so that no cell can be lit by spreading. Only a cell that
    # was extinguished at some point is allowed to relight, and this one never was.
    fire_at(model, (4, 4)).extinguish()
    cell = fire_at(model, (8, 8))
    assert not cell.was_extinguished

    for _ in range(3):
        model.step()
    assert not cell.is_burning()


def test_a_burnt_out_cell_does_not_relight(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, NUM_AGENTS=0, NUM_OUT_BUILDINGS=0,
                       BASE_POSITION=(1, 1), REIGNITION_DELAY=0, FIRE_SPREAD_SPEED=1,
                       SPONTANEOUS_REIGNITION_PROB=1.0)
    cell = fire_at(model, (8, 8))
    cell.extinguish()
    cell.fuel = 0  # nothing left to burn

    for _ in range(3):
        model.step()
    assert not cell.is_burning()


# --- the home base ----------------------------------------------------------


def test_the_run_is_lost_once_the_base_has_burned_for_bhp_steps(make_model):
    # the base is put on the centre cell, which is where the initial fire is lit
    model = make_model(ACTIVATE_FIREFIGHTING=True, NUM_AGENTS=0, NUM_OUT_BUILDINGS=0,
                       BASE_POSITION=(4, 4), BHP=3, FIRE_SPREAD_SPEED=1)
    assert fire_at(model, (4, 4)).is_burning()

    # damage is cumulative rather than consecutive: a burning cell whose neighbours are not alight yet goes
    # out for a step and catches again, so the base collects its damage over several visits from the fire
    for _ in range(40):
        if model.lost:
            break
        assert model.base.burning_steps < 3
        model.step()

    assert model.lost
    assert model.base.burning_steps >= 3
    assert not model.running


def test_the_base_survives_while_it_is_not_burning(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, NUM_AGENTS=0, NUM_OUT_BUILDINGS=0,
                       BASE_POSITION=(0, 0), BHP=2, FIRE_SPREAD_SPEED=1)
    for _ in range(2):
        model.step()
    assert model.base.burning_steps == 0
    assert not model.lost


def test_only_one_uav_refills_at_a_time(make_model):
    # three UAVs start stacked on the base, all empty, and compete for the single refilling slot.
    # Fuel is off so that one serve() call is a whole visit, see the footprint test above.
    model = make_model(ACTIVATE_FIREFIGHTING=True, ACTIVATE_FUEL=False, BASE_POSITION=(2, 2),
                       NUM_AGENTS=3, NUM_OUT_BUILDINGS=0, BASE_REFILL_STEPS=1, BASE_CAPACITY=1)
    crew = uavs_of(model)
    for uav in crew:
        uav.water = 0

    served = [model.base.serve(uav) for uav in crew]
    assert served == [True, False, False]
    assert [uav.has_water() for uav in crew] == [True, False, False]

    # the slot is freed at the base's next step, and the next UAV is served then
    model.base.step()
    assert model.base.serve(crew[1]) is True


def test_a_refill_takes_the_configured_number_of_steps(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), NUM_AGENTS=1,
                       NUM_OUT_BUILDINGS=0, BASE_REFILL_STEPS=3)
    uav = uavs_of(model)[0]
    uav.water = 0

    assert model.base.serve(uav) is False
    assert model.base.serve(uav) is False
    assert model.base.serve(uav) is True
    assert uav.has_water()


def test_a_uav_that_leaves_mid_refill_frees_the_slot(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), NUM_AGENTS=2,
                       NUM_OUT_BUILDINGS=0, BASE_REFILL_STEPS=5)
    first, second = uavs_of(model)
    first.water = 0
    second.water = 0

    model.base.serve(first)
    assert first.unique_id in model.base.serving

    model.grid.move_agent(first, (0, 0))  # flies away before finishing
    model.base.step()
    assert model.base.serving == {}
    assert model.base.serve(second) is False  # started its own refill, slot now taken by the second UAV
    assert second.unique_id in model.base.serving


def test_a_full_uav_does_not_take_a_refill_slot(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(2, 2), NUM_AGENTS=1,
                       NUM_OUT_BUILDINGS=0)
    uav = uavs_of(model)[0]
    assert uav.has_water()
    assert model.base.serve(uav) is False
    assert model.base.serving == {}


# --- out buildings ----------------------------------------------------------


def test_an_out_building_is_destroyed_after_burning_for_its_hp(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, NUM_AGENTS=0, NUM_OUT_BUILDINGS=1,
                       BASE_POSITION=(0, 0), OUT_BUILDING_HP=2, FIRE_SPREAD_SPEED=1)
    building = model.out_buildings[0]
    fire_at(model, building.pos).burning = True

    building.step()
    assert not building.destroyed
    building.step()
    assert building.destroyed
    assert model.buildings_lost == 1


def test_an_out_building_on_an_unburnt_cell_is_untouched(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, NUM_AGENTS=0, NUM_OUT_BUILDINGS=1,
                       BASE_POSITION=(0, 0), OUT_BUILDING_HP=1)
    building = model.out_buildings[0]
    fire_at(model, building.pos).burning = False

    building.step()
    assert not building.destroyed
    assert model.buildings_lost == 0


def test_a_destroyed_building_is_only_counted_once(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, NUM_AGENTS=0, NUM_OUT_BUILDINGS=1,
                       BASE_POSITION=(0, 0), OUT_BUILDING_HP=1)
    building = model.out_buildings[0]
    fire_at(model, building.pos).burning = True

    for _ in range(5):
        building.step()
    assert model.buildings_lost == 1


# --- observations passed to the policies ------------------------------------


def test_observations_carry_the_extension_state(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(4, 4), NUM_AGENTS=1,
                       NUM_OUT_BUILDINGS=0)
    observation = model.observations()[0]
    assert observation.has_water is True
    assert observation.base_pos == (4, 4)
    assert observation.at_base()

    uavs_of(model)[0].water = 0
    assert model.observations()[0].has_water is False


def test_observations_report_visible_buildings(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=True, BASE_POSITION=(4, 4), NUM_AGENTS=1,
                       NUM_OUT_BUILDINGS=0, UAV_OBSERVATION_RADIUS=2)
    # place a building the UAV can see, and one it cannot
    for position in ((5, 5), (0, 0)):
        building = agents.OutBuilding(model.unique_agents_id, model)
        model.unique_agents_id += 1
        model.grid.place_agent(building, position)
        model.out_buildings.append(building)

    assert model.observations()[0].building_positions == [(5, 5)]


def test_observations_stay_plain_when_the_extension_is_off(make_model):
    model = make_model(ACTIVATE_FIREFIGHTING=False, NUM_AGENTS=1)
    observation = model.observations()[0]
    assert observation.has_water is False
    assert observation.base_pos is None
    assert observation.building_positions == []
