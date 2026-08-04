"""Tests for the end of batch summary.

These exist because of a bug that got all the way to a run: RunResult.planner was renamed and
log_summary() was left reading the old name, so every managed batch raised AttributeError *after* the runs
had finished -- late enough that the runs themselves looked fine, and late enough to stop --output ever
being written. Nothing caught it, because nothing called log_summary() with a managed result.

The summary reads a dozen fields off RunResult and formats them, so the cheapest thing that would have
caught it is simply calling it. Any field that stops existing raises here.
"""

# python libraries

import logging

import pytest

# own python modules

from sim.cli.reporting import log_summary
from sim.cli.runner import RunResult


@pytest.fixture
def log():
    return logging.getLogger("wildfire.test.summary")


def result(**overrides):
    """A finished run, with every field the summary might read set to something plausible."""
    fields = dict(
        run_id=0, seed=1, steps_completed=30, wall_time_s=0.5,
        mr1_per_uav=[1.0, 2.0], mr1_total=3.0, mr2=7,
        collisions=1, uavs_lost=1, uavs_out_of_fuel=1, fuel_remaining=[10.0, 20.0],
        burning_cells_final=4, burned_out_cells_final=9,
        fire_start_pos=[5, 5], fire_start_step=3,
        water_drops=2, cells_extinguished=6, refills=1,
        buildings_lost=1, buildings_total=3, base_burning_steps=2,
        firefighting=True, lost=False,
    )
    fields.update(overrides)
    return RunResult(**fields)


def managed(**overrides):
    fields = dict(
        managing=True, managing_system="heuristic", managing_location="local",
        managing_components={"monitor": "default", "analyzer": "heuristic", "planner": "heuristic",
                             "executor": "default", "knowledge": "default"},
        adaptations=5,
        policy_steps={"firefighter": 60, "defend-base": 40},
        allocation_final={"0": "firefighter"},
        directives_rejected=0, managing_failures=0,
    )
    fields.update(overrides)
    return result(**fields)


# --- the regression ---------------------------------------------------------


def test_a_managed_batch_can_be_summarised(log):
    """The one that was missing. A stale field name raises AttributeError here and nowhere else."""
    log_summary([managed()], elapsed=1.0, log=log)


def test_a_remote_batch_can_be_summarised(log):
    # a remote run reports no composition, because the components are the server's
    log_summary([managed(managing_system="remote", managing_location="remote",
                         managing_components={}, managing_failures=3)], elapsed=1.0, log=log)


def test_a_batch_that_lost_its_managing_system_can_be_summarised(log):
    log_summary([managed(managing_failures=30, directives_rejected=2)], elapsed=1.0, log=log)


# --- the arms of an A/B, which is what the summary is for --------------------


def test_an_unmanaged_batch_can_be_summarised(log):
    log_summary([result(managing=False, managing_system="none")], elapsed=1.0, log=log)


def test_a_mixed_batch_can_be_summarised(log):
    log_summary([managed(), result(managing=False, managing_system="none")], elapsed=1.0, log=log)


# --- the edges ---------------------------------------------------------------


def test_an_empty_batch_can_be_summarised(log):
    log_summary([], elapsed=0.0, log=log)


def test_a_failed_run_can_be_summarised(log):
    failed = RunResult(run_id=1, seed=None, steps_completed=0, wall_time_s=0.1, error="boom")
    log_summary([failed], elapsed=1.0, log=log)


def test_a_batch_of_nothing_but_failures_can_be_summarised(log):
    failed = RunResult(run_id=1, seed=None, steps_completed=0, wall_time_s=0.1, error="boom")
    log_summary([failed, failed], elapsed=1.0, log=log)


def test_a_managed_batch_with_no_uav_steps_can_be_summarised(log):
    # a run that ended before anything flew; the percentage line divides by the total, so it must be skipped
    log_summary([managed(policy_steps={})], elapsed=1.0, log=log)


def test_a_run_without_the_firefighting_extension_can_be_summarised(log):
    log_summary([result(firefighting=False, buildings_total=0, fuel_remaining=[])], elapsed=1.0, log=log)


# --- what it actually reports ------------------------------------------------


def test_the_summary_names_the_managing_system_and_where_it_was(log, caplog):
    with caplog.at_level(logging.INFO, logger=log.name):
        log_summary([managed(managing_system="defensive", managing_location="remote")],
                    elapsed=1.0, log=log)
    assert "defensive" in caplog.text
    assert "remote" in caplog.text


def test_the_summary_names_what_the_managing_system_was_made_of(log, caplog):
    """--mape can produce a batch that no registered name describes, so the name alone is not enough."""
    with caplog.at_level(logging.INFO, logger=log.name):
        log_summary([managed(managing_components={"planner": "static", "analyzer": "cautious"})],
                    elapsed=1.0, log=log)
    assert "P=static" in caplog.text
    assert "A=cautious" in caplog.text


def test_the_summary_reports_uav_steps_per_policy(log, caplog):
    with caplog.at_level(logging.INFO, logger=log.name):
        log_summary([managed()], elapsed=1.0, log=log)
    assert "firefighter=60" in caplog.text
    assert "defend-base=40" in caplog.text


def test_the_summary_warns_when_the_managing_system_was_not_obeyed(log, caplog):
    with caplog.at_level(logging.WARNING, logger=log.name):
        log_summary([managed(directives_rejected=4, managing_failures=2)], elapsed=1.0, log=log)
    assert "4 directive(s) refused" in caplog.text
    assert "2 evaluation(s) unanswered" in caplog.text


def test_the_summary_is_quiet_about_a_healthy_managed_batch(log, caplog):
    with caplog.at_level(logging.WARNING, logger=log.name):
        log_summary([managed()], elapsed=1.0, log=log)
    assert "refused" not in caplog.text
