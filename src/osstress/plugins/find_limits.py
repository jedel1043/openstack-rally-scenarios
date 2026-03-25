"""OsStress Rally scenario plugin — automated limit finding.

This plugin wraps any Rally scenario and runs it with progressively
increasing iteration counts, checking configurable SLA thresholds after
each step.  The first step that violates a threshold is recorded as the
service's operational limit.

Instead of reimplementing iteration execution, each step delegates to a
real Rally runner instance (``serial``, ``constant``, ``rps``, …).  The
caller supplies a ``runner`` dict — identical in shape to the native
``"runner"`` block in a Rally task file — and this plugin injects the
computed ``times`` value before handing off to the runner.  This means
you get the runner's full feature set (concurrency, RPS throttling,
timeouts, …) at every load level for free.

Inspired by the external ``run_limits.py`` tool, but implemented as a
native Rally scenario plugin so that all results — including per-step
timing series and the discovered limit — appear in the standard Rally
HTML report.
"""

from __future__ import annotations

import copy
import logging
import time
from typing import Any

from rally.task import atomic, scenario, validation

from rally_openstack.task import scenario as os_scenario

from common import DEFAULT_RUNNER, run_via_runner

LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SLA parsing
# ---------------------------------------------------------------------------


def _parse_sla(
    sla: dict[str, Any],
) -> tuple[float | None, float | None, float | None]:
    """Extract SLA thresholds from a Rally-native ``sla`` dict.

    The dict uses the same keys and format as Rally's top-level ``"sla"``
    block:

    * ``failure_rate``              — ``{"max": <0–100>}`` percentage.
    * ``max_avg_duration``          — ``<float>`` seconds.
    * ``max_seconds_per_iteration`` — ``<float>`` seconds.

    Returns ``(max_avg_duration, max_seconds_per_iteration,
    max_failure_rate)`` where *max_failure_rate* is a **fraction**
    (0.0–1.0) for internal use, and any omitted criterion is ``None``.
    """
    max_avg_duration: float | None = None
    max_seconds_per_iteration: float | None = None
    max_failure_rate: float | None = None

    if "max_avg_duration" in sla:
        max_avg_duration = float(sla["max_avg_duration"])

    if "max_seconds_per_iteration" in sla:
        max_seconds_per_iteration = float(sla["max_seconds_per_iteration"])

    if "failure_rate" in sla:
        fr = sla["failure_rate"]
        if isinstance(fr, dict):
            # Native Rally format: {"max": <percentage>}
            max_failure_rate = float(fr["max"]) / 100.0
        else:
            # Accept a bare number as a percentage for convenience.
            max_failure_rate = float(fr) / 100.0

    return max_avg_duration, max_seconds_per_iteration, max_failure_rate


# ---------------------------------------------------------------------------
# SLA evaluation
# ---------------------------------------------------------------------------


def _evaluate_sla(
    step_results: list[dict[str, Any]],
    max_avg_duration: float | None,
    max_seconds_per_iteration: float | None,
    max_failure_rate: float | None,
) -> tuple[bool, str]:
    """Check the results of a single step against SLA thresholds.

    *step_results* is a list of :class:`ScenarioRunnerResult` dicts
    where ``result["error"]`` is a ``list[str]`` (empty means success).

    Returns ``(passed, reason)`` where *reason* describes the first
    threshold that was violated (empty string when all passed).
    """
    if not step_results:
        return True, ""

    durations = [r["duration"] for r in step_results]
    # ScenarioRunnerResult["error"] is list[str]; truthy when non-empty.
    failures = sum(1 for r in step_results if r["error"])
    total = len(step_results)
    failure_rate = failures / total

    if max_failure_rate is not None and failure_rate > max_failure_rate:
        return False, (
            f"failure_rate {failure_rate:.2%} > max {max_failure_rate:.2%}"
        )

    avg_duration = sum(durations) / total
    if max_avg_duration is not None and avg_duration > max_avg_duration:
        return False, (
            f"avg_duration {avg_duration:.4f}s > max {max_avg_duration:.4f}s"
        )

    worst = max(durations)
    if max_seconds_per_iteration is not None and worst > max_seconds_per_iteration:
        return False, (
            f"max_duration {worst:.4f}s > max {max_seconds_per_iteration:.4f}s"
        )

    return True, ""


# ---------------------------------------------------------------------------
# Rally scenario plugin
# ---------------------------------------------------------------------------


@validation.add("required_platform", platform="openstack", users=True)
@os_scenario.configure(
    name="OsStress.find_limits",
    platform="openstack",
)
class FindLimits(os_scenario.OpenStackScenario):
    """Incrementally increase load until SLA thresholds are breached.

    This plugin wraps any available Rally scenario and runs it with a
    growing number of iterations per step, starting at *min_times* and
    increasing by *step* after each passing round, up to *max_times*.

    Each step delegates to a real Rally **runner** instance whose
    configuration is supplied via the ``runner`` argument.  The plugin
    injects the computed ``times`` value into that configuration before
    every step, so any runner that accepts ``times`` (``serial``,
    ``constant``, ``rps``, …) can be used.  This gives you full access
    to concurrency, RPS throttling, timeouts and other runner features
    at every load level.

    After every step the collected results are evaluated against the
    configured SLA thresholds.  As soon as a threshold is violated the
    search stops and the **last passing step** is recorded as the
    service limit.

    Performance data — average duration, maximum duration and failure
    rate at each load level — are exported as Rally output charts for
    visualisation in the HTML report.

    Execution flow:

    1. Set ``current_times = min_times``.
    2. Run the wrapped scenario ``current_times`` times using the
       configured runner.
    3. Evaluate SLA thresholds against the step's results.
    4. If all thresholds pass, record the step, sleep, increment
       ``current_times`` by ``step`` and go to 2.
    5. If any threshold is violated, record the failing step and stop.
    6. Emit charts and tables to the Rally report.
    """

    def run(
        self,
        scenario_name: str,
        scenario_args: dict[str, Any] | None = None,
        min_times: int = 1,
        max_times: int = 100,
        step: int = 1,
        sleep: float = 1.0,
        sla: dict[str, Any] | None = None,
        runner: dict[str, Any] | None = None,
    ) -> None:
        """Execute the limit-finding workload.

        :param scenario_name: Full Rally scenario plugin name, e.g.
            ``"Authenticate.keystone"``.
        :param scenario_args: Keyword arguments forwarded to the inner
            scenario's ``run()`` method.
        :param min_times: Number of iterations for the first step.
        :param max_times: Maximum number of iterations per step.  The
            search stops after this level is tested regardless of
            whether a limit was found.
        :param step: How many additional iterations to add after each
            passing step.
        :param sleep: Seconds to pause between consecutive steps to
            allow the system under test to settle.
        :param sla: SLA criteria dict using the same format as Rally's
            native top-level ``"sla"`` block.  Supported keys:

            * ``failure_rate`` — ``{"max": <0–100>}`` maximum failure
              **percentage** (0 = no failures allowed).
            * ``max_avg_duration`` — ``<float>`` maximum average
              iteration duration in seconds.
            * ``max_seconds_per_iteration`` — ``<float>`` maximum
              single-iteration duration in seconds.

            If omitted or empty the search runs through all steps up to
            *max_times* without stopping early.
        :param runner: Runner configuration dict, identical in shape to
            the native ``"runner"`` block in a Rally task file.  The
            ``"times"`` field is **ignored** (overridden per step).
            Defaults to ``{"type": "serial"}`` when omitted.

            Example — run each step with 4 concurrent workers::

                {"type": "constant", "concurrency": 4}

            Example — run each step at 50 RPS::

                {"type": "rps", "rps": 50}
        """
        scenario_args = scenario_args or {}
        sla = sla or {}
        runner_cfg = dict(runner) if runner else dict(DEFAULT_RUNNER)

        # Validate early so we fail before the stepping loop starts.
        scenario.Scenario.get(scenario_name)

        if min_times < 1:
            raise ValueError("min_times must be >= 1")
        if max_times < min_times:
            raise ValueError("max_times must be >= min_times")
        if step < 1:
            raise ValueError("step must be >= 1")

        max_avg_duration, max_seconds_per_iteration, max_failure_rate = (
            _parse_sla(sla)
        )

        task_obj = self.context["task"]
        # Deep-copy the context once so that inner runners can mutate
        # their own copies (via _get_scenario_context) without affecting
        # us.  We keep a stable snapshot across all steps.
        inner_context = copy.deepcopy(self.context)

        # ---------------------------------------------------------------
        # Stepping loop
        # ---------------------------------------------------------------
        all_steps: list[dict[str, Any]] = []
        current_times = min_times
        limit_times: int | None = None  # last passing times value

        while current_times <= max_times:
            step_label = f"find_limits.step@{current_times}"

            LOG.info(
                "FindLimits: running %s with %d iterations "
                "(runner: %s)",
                scenario_name,
                current_times,
                runner_cfg.get("type", "serial"),
            )

            with atomic.ActionTimer(self, step_label):
                step_results = run_via_runner(
                    scenario_name=scenario_name,
                    scenario_args=scenario_args,
                    runner_cfg=runner_cfg,
                    times=current_times,
                    task=task_obj,
                    context=inner_context,
                )

            # Compute stats for this step
            durations = [r["duration"] for r in step_results]
            failures = sum(1 for r in step_results if r["error"])
            total = len(step_results)
            avg_dur = sum(durations) / total if total else 0.0
            max_dur = max(durations) if durations else 0.0
            min_dur = min(durations) if durations else 0.0
            failure_rate = failures / total if total else 0.0

            passed, reason = _evaluate_sla(
                step_results,
                max_avg_duration=max_avg_duration,
                max_seconds_per_iteration=max_seconds_per_iteration,
                max_failure_rate=max_failure_rate,
            )

            step_info: dict[str, Any] = {
                "times": current_times,
                "total": total,
                "failures": failures,
                "failure_rate": round(failure_rate, 4),
                "avg_duration": round(avg_dur, 4),
                "min_duration": round(min_dur, 4),
                "max_duration": round(max_dur, 4),
                "passed": passed,
                "reason": reason,
            }
            all_steps.append(step_info)

            LOG.info(
                "FindLimits: step %d — avg=%.4fs max=%.4fs "
                "failures=%d/%d passed=%s%s",
                current_times,
                avg_dur,
                max_dur,
                failures,
                total,
                passed,
                f" ({reason})" if reason else "",
            )

            if not passed:
                break

            limit_times = current_times
            current_times += step

            # Sleep between steps to let the system settle.
            if current_times <= max_times and sleep > 0:
                time.sleep(sleep)

        # ---------------------------------------------------------------
        # Emit output
        # ---------------------------------------------------------------
        self._emit_output(
            all_steps=all_steps,
            limit_times=limit_times,
            scenario_name=scenario_name,
            runner_cfg=runner_cfg,
            max_avg_duration=max_avg_duration,
            max_seconds_per_iteration=max_seconds_per_iteration,
            max_failure_rate=max_failure_rate,
        )

    # -------------------------------------------------------------------
    # Output helpers
    # -------------------------------------------------------------------

    def _emit_output(
        self,
        all_steps: list[dict[str, Any]],
        limit_times: int | None,
        scenario_name: str,
        runner_cfg: dict[str, Any],
        max_avg_duration: float | None,
        max_seconds_per_iteration: float | None,
        max_failure_rate: float | None,
    ) -> None:
        """Attach all collected data to the Rally report."""

        if not all_steps:
            return

        x_values = [s["times"] for s in all_steps]

        # --- Duration vs load chart (Lines) --------------------------------
        avg_series = [[x, s["avg_duration"]] for x, s in zip(x_values, all_steps)]
        max_series = [[x, s["max_duration"]] for x, s in zip(x_values, all_steps)]
        min_series = [[x, s["min_duration"]] for x, s in zip(x_values, all_steps)]

        duration_data: list[list[Any]] = [
            ["Avg Duration", avg_series],
            ["Max Duration", max_series],
            ["Min Duration", min_series],
        ]

        # Add threshold lines if configured
        if max_avg_duration is not None:
            duration_data.append([
                "SLA: max avg",
                [[x_values[0], max_avg_duration], [x_values[-1], max_avg_duration]],
            ])
        if max_seconds_per_iteration is not None:
            duration_data.append([
                "SLA: max per iteration",
                [[x_values[0], max_seconds_per_iteration],
                 [x_values[-1], max_seconds_per_iteration]],
            ])

        self.add_output(complete={
            "title": f"Duration vs Load – {scenario_name}",
            "description": (
                "Iteration durations (avg / max / min) at each load level.  "
                "Dashed lines show configured SLA thresholds."
            ),
            "chart_plugin": "Lines",
            "data": duration_data,
            "label": "Duration (s)",
            "axis_label": "Iterations per step",
        })

        # --- Failure rate vs load chart (Lines) ----------------------------
        fail_series = [
            [x, round(s["failure_rate"] * 100, 2)]
            for x, s in zip(x_values, all_steps)
        ]
        fail_data: list[list[Any]] = [["Failure Rate", fail_series]]

        if max_failure_rate is not None:
            fail_data.append([
                "SLA: max failure rate",
                [[x_values[0], round(max_failure_rate * 100, 2)],
                 [x_values[-1], round(max_failure_rate * 100, 2)]],
            ])

        self.add_output(complete={
            "title": f"Failure Rate vs Load – {scenario_name}",
            "description": (
                "Percentage of failed iterations at each load level"
            ),
            "chart_plugin": "Lines",
            "data": fail_data,
            "label": "Failure Rate (%)",
            "axis_label": "Iterations per step",
        })

        # --- Summary table -------------------------------------------------
        table_rows: list[list[str]] = []
        for s in all_steps:
            status = "PASS" if s["passed"] else "FAIL"
            table_rows.append([
                str(s["times"]),
                str(s["total"]),
                str(s["failures"]),
                f"{s['failure_rate']:.2%}",
                f"{s['min_duration']:.4f}",
                f"{s['avg_duration']:.4f}",
                f"{s['max_duration']:.4f}",
                status,
                s["reason"] or "—",
            ])

        self.add_output(complete={
            "title": f"Limit Search Summary – {scenario_name}",
            "description": "Per-step statistics and SLA evaluation results",
            "chart_plugin": "Table",
            "data": {
                "cols": [
                    "Iterations",
                    "Total",
                    "Failures",
                    "Failure Rate",
                    "Min (s)",
                    "Avg (s)",
                    "Max (s)",
                    "SLA",
                    "Reason",
                ],
                "rows": table_rows,
            },
        })

        # --- Outcome pie ---------------------------------------------------
        passed_steps = sum(1 for s in all_steps if s["passed"])
        failed_steps = len(all_steps) - passed_steps

        self.add_output(complete={
            "title": "Step Outcomes",
            "description": "Number of passing vs failing load steps",
            "chart_plugin": "Pie",
            "data": [
                ["Passed", passed_steps],
                ["Failed", failed_steps],
            ],
        })

        # --- Limit result table --------------------------------------------
        if limit_times is not None:
            limit_msg = (
                f"The last step that passed all SLA thresholds had "
                f"{limit_times} iterations."
            )
        else:
            limit_msg = (
                "No step passed all SLA thresholds — even the minimum "
                "load level violated a constraint."
            )

        sla_desc_parts: list[str] = []
        if max_avg_duration is not None:
            sla_desc_parts.append(f"max_avg_duration={max_avg_duration}s")
        if max_seconds_per_iteration is not None:
            sla_desc_parts.append(
                f"max_seconds_per_iteration={max_seconds_per_iteration}s"
            )
        if max_failure_rate is not None:
            sla_desc_parts.append(f"max_failure_rate={max_failure_rate:.2%}")

        runner_type = runner_cfg.get("type", "serial")
        runner_desc_parts = [f"type={runner_type}"]
        for key in ("concurrency", "rps", "timeout"):
            if key in runner_cfg:
                runner_desc_parts.append(f"{key}={runner_cfg[key]}")

        self.add_output(complete={
            "title": f"Discovered Limit – {scenario_name}",
            "description": limit_msg,
            "chart_plugin": "Table",
            "data": {
                "cols": ["Property", "Value"],
                "rows": [
                    ["Scenario", scenario_name],
                    ["Limit (iterations)", str(limit_times) if limit_times is not None else "N/A"],
                    ["Steps tested", str(len(all_steps))],
                    ["Runner", ", ".join(runner_desc_parts)],
                    ["SLA thresholds", ", ".join(sla_desc_parts) if sla_desc_parts else "none"],
                    ["Result", limit_msg],
                ],
            },
        })