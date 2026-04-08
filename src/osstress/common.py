"""Shared helpers for OsStress Rally scenario plugins."""

import logging
from typing import Any

from rally.task import runner as rally_runner

LOG = logging.getLogger(__name__)

DEFAULT_RUNNER: dict[str, Any] = {"type": "serial"}


def collect_runner_results(
    runner_obj: rally_runner.ScenarioRunner,
) -> list[dict[str, Any]]:
    """Drain all results from a finished :class:`ScenarioRunner`.

    After ``runner_obj.run()`` returns, every
    :class:`ScenarioRunnerResult` is sitting in ``runner_obj.result_queue``
    grouped into batches.  This helper flattens them into a single list.
    """
    results: list[dict[str, Any]] = []
    while runner_obj.result_queue:
        results.extend(runner_obj.result_queue.popleft())
    return results


def run_via_runner(
    scenario_name: str,
    scenario_args: dict[str, Any],
    runner_cfg: dict[str, Any],
    times: int,
    task: Any,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Execute a scenario through a Rally runner.

    Returns the flat list of :class:`ScenarioRunnerResult` dicts
    produced by the runner.
    """
    step_cfg = dict(runner_cfg)
    step_cfg["times"] = times

    runner_cls = rally_runner.ScenarioRunner.get(step_cfg["type"])
    runner_obj = runner_cls(task=task, config=step_cfg)
    runner_obj.run(scenario_name, context, scenario_args)

    return collect_runner_results(runner_obj)
