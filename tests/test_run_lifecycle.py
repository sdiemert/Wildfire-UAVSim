"""Tests for how long a run lasts and what reset() clears.

Two things about the run as a whole rather than about any agent in it: a run stops after exactly
BATCH_SIZE simulated steps, and reset() puts the model back to the state it was built in, so a run
restarted in place does not inherit the previous one's monitoring scores.

The run-length tests switch the firefighting extension off, because the step budget is not the only thing
that can stop a run: losing the home base stops it too, and on the 9x9 grid the fixture builds, the fire
starts a couple of cells from a base with nobody defending it. That went from harmless to a coin flip when
BHP came down to 4 and the fire began spreading every step -- the base burned down on exactly the step the
budget ran out, and the run stopped for whichever reason got there first. With no base there is only one
way for a run to end, which is the one these tests are about.
"""


# --- run length -------------------------------------------------------------


def test_run_stops_after_exactly_batch_size_steps(make_model):
    """BATCH_SIZE is the number of steps simulated, not one less and not one more."""
    model = make_model(BATCH_SIZE=5, NUM_AGENTS=0, ACTIVATE_FIREFIGHTING=False)

    calls = 0
    while model.running and calls < 50:
        model.step()
        calls += 1

    assert model.evaluation_timesteps_counter == 5
    # the last call is the one that finds the run over and clears 'running', so it simulates nothing
    assert calls == 6


def test_running_stays_set_until_the_last_step(make_model):
    """A run of n steps is still running after n - 1 of them."""
    model = make_model(BATCH_SIZE=3, NUM_AGENTS=0, ACTIVATE_FIREFIGHTING=False)

    for _ in range(3):
        assert model.running
        model.step()

    assert model.evaluation_timesteps_counter == 3


def test_a_single_step_run_simulates_one_step(make_model):
    """The smallest run there is, where an off-by-one is easiest to see."""
    model = make_model(BATCH_SIZE=1, NUM_AGENTS=0, ACTIVATE_FIREFIGHTING=False)

    model.step()
    assert model.evaluation_timesteps_counter == 1

    model.step()
    assert not model.running
    assert model.evaluation_timesteps_counter == 1


# --- reset ------------------------------------------------------------------


def test_reset_clears_the_monitoring_metrics(make_model):
    """MR1 and MR2 belong to one run: restarting in place starts them again from nothing."""
    model = make_model(NUM_AGENTS=3)

    for _ in range(5):
        model.step()
    # the UAVs are launched together on the base, so they score MR2 from the first step
    model.MR1_LIST = [1.5, 2.5, 3.5]
    model.MR2_VALUE = 7

    model.reset()

    assert model.MR1_LIST == [0.0, 0.0, 0.0]
    assert model.MR2_VALUE == 0


def test_reset_clears_the_step_counter_and_keeps_the_model_running(make_model):
    model = make_model(BATCH_SIZE=3, NUM_AGENTS=0)

    while model.running:
        model.step()
    assert not model.running

    model.reset()

    assert model.running
    assert model.evaluation_timesteps_counter == 0


def test_reset_sizes_mr1_to_the_team(make_model):
    """MR1_LIST is indexed by place in the team, so it has to come back the right length."""
    model = make_model(NUM_AGENTS=4)

    model.reset()

    assert len(model.MR1_LIST) == 4
