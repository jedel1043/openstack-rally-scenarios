"""OsStress Rally scenario plugin — ``OsStress.split_stress``.

Runs a Rally scenario with a trigger fired at the midpoint.

All iterations are executed in a **single continuous run** so the request
rate stays constant.  A monitor thread watches progress and fires the
trigger command(s) as soon as half the iterations have started.  Results
are split into "before trigger" and "after trigger" by timestamp for
reporting.

The run delegates to a real Rally runner instance (``serial``,
``constant``, ``rps``, …) so you get the runner's full feature set
(concurrency, RPS throttling, timeouts, …) for free.

Host metrics (CPU, memory, I/O) are collected in a **background thread**
at a configurable ``snapshot_interval`` so that snapshots reflect the
system state while it is actually under load, not just at idle phase
boundaries.
"""

import copy
import logging
import shlex
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from common import DEFAULT_RUNNER, collect_runner_results
from metrics import (
    HostConnection,
    PersistentShell,
    build_rally_output_charts,
)
from rally.task import atomic, scenario
from rally.task.runner import ScenarioRunner

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CommandResult:
    """Result of a remote command execution on a single host."""

    host: str
    command: str
    returncode: int
    duration: float
    stdout: str = ""
    stderr: str = ""


def _remote_trigger(
    conn: HostConnection,
    command: str,
) -> CommandResult:
    """Execute *command* on the remote host and return execution details.

    Uses the transport-agnostic *reach_command* stored in *conn*.  This
    works for plain SSH, ``juju ssh``, ``kubectl exec``, or any other
    command prefix that accepts a shell command as a trailing argument.
    """
    cmd = list(conn.reach_command) + [command]
    logger.info(
        "Remote command on %s: %s",
        conn.label,
        " ".join(shlex.quote(c) for c in cmd),
    )

    # Trigger/cleanup commands may take longer than metric collection,
    # so we add a generous margin on top of the base command_timeout.
    trigger_timeout = conn.command_timeout + 90

    t0 = time.monotonic()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=trigger_timeout,
    )
    elapsed = time.monotonic() - t0

    cmd_result = CommandResult(
        host=conn.label,
        command=command,
        returncode=result.returncode,
        duration=round(elapsed, 4),
        stdout=result.stdout,
        stderr=result.stderr,
    )
    if result.returncode != 0:
        logger.warning(
            "Remote command on %s exited %d – stderr: %s",
            conn.label,
            result.returncode,
            result.stderr.strip()[:512],
        )
    return cmd_result


# Opaque handle returned by _remote_trigger_async — callers must pass it
# back to _collect_trigger_results to obtain the result-info dict.
_AsyncHandle = tuple[str, str, "subprocess.Popen[str]", float]


def _remote_trigger_async(
    conn: HostConnection,
    command: str,
) -> _AsyncHandle:
    """Launch *command* on the remote host **without waiting** for it.

    Returns an opaque handle that must be passed to
    :func:`_collect_trigger_results` to wait for completion and build the
    result-info dict.

    This is the non-blocking counterpart of :func:`_remote_trigger` and
    is intended for long-lived trigger commands (e.g. ``stress-ng``) that
    should keep running while the remaining iterations execute.
    """
    cmd = list(conn.reach_command) + [command]
    logger.info(
        "Background trigger on %s: %s",
        conn.label,
        " ".join(shlex.quote(c) for c in cmd),
    )
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return (conn.label, command, proc, time.monotonic())


def _collect_trigger_results(
    handles: list[_AsyncHandle],
) -> list[CommandResult]:
    """Terminate every async trigger and return result-info dicts.

    *handles* is a list of opaque handles returned by
    :func:`_remote_trigger_async`.  Each process that is still running
    is terminated immediately so the scenario can proceed to cleanup.
    """
    infos: list[CommandResult] = []
    for label, command, proc, t0 in handles:
        if proc.poll() is None:
            logger.info("Terminating background trigger on %s", label)
            proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
        else:
            stdout, stderr = proc.communicate()
        elapsed = time.monotonic() - t0
        info = CommandResult(
            host=label,
            command=command,
            returncode=proc.returncode if proc.returncode is not None else -1,
            duration=round(elapsed, 4),
            stdout=stdout or "",
            stderr=stderr or "",
        )
        if proc.returncode and proc.returncode != 0:
            logger.warning(
                "Background trigger on %s exited %d – stderr: %s",
                label,
                proc.returncode,
                (stderr or "").strip()[:512],
            )
        infos.append(info)
    return infos


@dataclass
class _Connection:
    """All the information needed to reach one target host."""

    label: str
    conn: HostConnection
    trigger_command: str = ""
    cleanup_command: str = ""


def _parse_reach_command(raw: str | list[str]) -> list[str]:
    """Normalise a *reach_command* value to a list of strings."""
    if isinstance(raw, str):
        return shlex.split(raw)
    return list(raw)


def _build_connections(
    hosts: list[dict[str, Any]],
    command_timeout: int,
) -> list[_Connection]:
    """Build :class:`_Connection` records from the *hosts* list.

    Returns a list of :class:`_Connection` objects carrying the label,
    :class:`HostConnection`, trigger command and cleanup command for each
    host.

    Each host entry must specify an explicit ``reach_command`` — the
    shell command prefix used to execute commands on that host (e.g.
    ``"juju ssh keystone/0 --"`` or
    ``["kubectl", "exec", "pod", "--", "bash", "-c"]``).

    Each entry may carry its own ``trigger_command`` and
    ``cleanup_command``.  Entries that omit either default to an empty
    string (no-op).  An entry may also explicitly set a command to
    ``null`` / empty string to skip it on that host (metrics are still
    collected).
    """
    conns: list[_Connection] = []
    for idx, entry in enumerate(hosts):
        if entry.get("host"):
            raise ValueError(
                f"hosts[{idx}] specifies 'host'; use 'reach_command' instead"
            )

        rc = entry.get("reach_command")
        if not rc:
            raise ValueError(f"hosts[{idx}] must contain 'reach_command'")

        rc_list = _parse_reach_command(rc)
        label = entry.get("label", rc if isinstance(rc, str) else " ".join(rc))
        ct = entry.get("command_timeout", command_timeout)
        conn = HostConnection(
            label=label,
            reach_command=rc_list,
            command_timeout=ct,
        )

        trig = entry.get("trigger_command", "")
        clean = entry.get("cleanup_command", "")
        conns.append(
            _Connection(
                label=label,
                conn=conn,
                trigger_command=trig,
                cleanup_command=clean,
            )
        )
    return conns


def _collect_all_snapshots(
    connections: list[_Connection],
    sample_label: str,
) -> dict[str, Any]:
    """Collect a metrics snapshot from every host, in parallel.

    Returns ``{host_label: HostMetricsSnapshot}``.
    """
    results: dict[str, Any] = {}
    if len(connections) == 1:
        e = connections[0]
        results[e.label] = e.conn.collect_snapshot(sample_label)
        return results

    with ThreadPoolExecutor(max_workers=len(connections)) as pool:
        futures = {
            pool.submit(e.conn.collect_snapshot, sample_label): e.label
            for e in connections
        }
        for fut in as_completed(futures):
            label = futures[fut]
            try:
                results[label] = fut.result()
            except Exception as exc:
                logger.warning("Metrics collection failed for %s: %s", label, exc)
    return results


# ---------------------------------------------------------------------------
# Background snapshot collector
# ---------------------------------------------------------------------------


class _SnapshotCollector:
    """Periodically collect host metrics in a background thread.

    The collector takes a snapshot from every host every
    *interval* seconds.  Each snapshot is labelled with the current
    *phase* (set via :meth:`set_phase`) and a monotonically
    increasing counter so that output charts show when each sample
    was taken relative to the execution flow.

    Usage::

        collector = _SnapshotCollector(connections, interval=5.0)
        collector.set_phase("first_half")
        with collector:          # starts background thread
            ...                  # run workload
            collector.set_phase("trigger")
            ...                  # fire trigger
        snaps = collector.snapshots   # read after context exits
    """

    def __init__(
        self,
        connections: list[_Connection],
        interval: float,
        use_persistent_shell: bool = True,
    ) -> None:
        self._connections = connections
        self._interval = interval
        self._use_persistent_shell = use_persistent_shell
        self._stop = threading.Event()
        self._phase = "idle"
        self._counter = 0
        self._snapshots: dict[str, list] = {e.label: [] for e in connections}
        self._thread: threading.Thread | None = None
        self._shells: list[PersistentShell] = []

    # -- phase control ------------------------------------------------------

    def set_phase(self, phase: str) -> None:
        """Update the phase label applied to subsequent snapshots."""
        self._phase = phase

    def start(self) -> None:
        if self._use_persistent_shell:
            for e in self._connections:
                shell = PersistentShell(
                    e.conn.reach_command,
                    command_timeout=e.conn.command_timeout,
                )
                try:
                    shell.open()
                    e.conn.shell = shell
                    self._shells.append(shell)
                    logger.debug("Persistent shell opened for %s", e.conn.label)
                except Exception:
                    logger.warning(
                        "Failed to open persistent shell for %s; "
                        "falling back to per-command subprocesses",
                        e.conn.label,
                        exc_info=True,
                    )
        else:
            logger.info(
                "Persistent shells disabled; each snapshot will spawn "
                "a fresh subprocess per host"
            )

        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="snapshot-collector",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

        # Tear down persistent shells and detach them from connections
        # so that subsequent subprocess-based calls are unaffected.
        for shell in self._shells:
            try:
                shell.close()
            except Exception:
                logger.debug("Error closing persistent shell", exc_info=True)
        self._shells.clear()
        for e in self._connections:
            e.conn.shell = None

    def __enter__(self) -> "_SnapshotCollector":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.stop()

    # -- results ------------------------------------------------------------

    @property
    def snapshots(self) -> dict[str, list]:
        """Per-host snapshot lists.  Read after :meth:`stop`."""
        return self._snapshots

    # -- internal -----------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._counter += 1
            sample_label = f"{self._phase} #{self._counter}"
            try:
                results = _collect_all_snapshots(
                    self._connections,
                    sample_label,
                )
                for host_label, snap in results.items():
                    self._snapshots[host_label].append(snap)
            except Exception:
                logger.warning(
                    "Background snapshot #%d failed",
                    self._counter,
                    exc_info=True,
                )
            self._stop.wait(self._interval)


def _run_commands_on_hosts(
    targets: list[tuple[str, HostConnection, str]],
    phase_name: str,
) -> list[CommandResult]:
    """Fire a command on every host in *targets*, in parallel.

    *targets* is a list of ``(label, HostConnection, command)`` triples.
    Entries whose command is empty or ``None`` are silently skipped.
    Returns a list of result-info dicts (one per host that was executed).
    *phase_name* is used only for log messages (e.g. ``"trigger"`` or
    ``"cleanup"``).
    """
    to_run = [(label, conn, cmd) for label, conn, cmd in targets if cmd]
    if not to_run:
        return []

    if len(to_run) == 1:
        _label, conn, cmd = to_run[0]
        return [_remote_trigger(conn, cmd)]

    infos: list[CommandResult] = []
    with ThreadPoolExecutor(max_workers=len(to_run)) as pool:
        futures = {
            pool.submit(_remote_trigger, conn, cmd): label
            for label, conn, cmd in to_run
        }
        for fut in as_completed(futures):
            label = futures[fut]
            try:
                infos.append(fut.result())
            except Exception as exc:
                logger.warning("%s failed for %s: %s", phase_name, label, exc)
                infos.append(
                    CommandResult(
                        host=label,
                        command="(failed)",
                        returncode=-1,
                        duration=0,
                        stderr=str(exc),
                    )
                )
    return infos


def _start_triggers_async(
    connections: list[_Connection],
) -> list[_AsyncHandle]:
    """Launch trigger commands on all hosts without blocking.

    Returns a list of opaque handles.  Pass them to
    :func:`_collect_trigger_results` after the second half of iterations
    to obtain the result-info dicts.  Connections whose trigger command
    is empty are silently skipped.
    """
    handles: list[_AsyncHandle] = []
    for e in connections:
        if not e.trigger_command:
            continue
        handles.append(_remote_trigger_async(e.conn, e.trigger_command))
    return handles


def _cleanup_all(
    connections: list[_Connection],
) -> list[CommandResult]:
    """Fire the cleanup command on every host, in parallel."""
    targets = [(e.label, e.conn, e.cleanup_command) for e in connections]
    return _run_commands_on_hosts(targets, "Cleanup")


# ---------------------------------------------------------------------------
# Rally scenario plugin
# ---------------------------------------------------------------------------


@scenario.configure(
    name="OsStress.split_stress",
)
class SplitStress(scenario.Scenario):
    """Run a Rally scenario with a trigger fired at the midpoint.

    All iterations are executed in a **single continuous run** so the
    request rate stays constant — there is no gap between a "first half"
    and a "second half".  A background monitor thread watches runner
    progress and fires the trigger command(s) as soon as half the
    iterations have started.  After the run finishes, results are
    partitioned into "before trigger" and "after trigger" by timestamp.

    Target hosts are specified via the ``hosts`` parameter — a list of
    dicts.  Each host entry must specify a ``reach_command`` — the shell
    command prefix used to reach that host (e.g. ``"juju ssh keystone/0
    --"`` or ``["kubectl", "exec", "pod", "--"]``).  Each entry carries
    its own ``trigger_command`` and ``cleanup_command``.

    Host metrics (CPU, memory, I/O) are collected in a **background
    thread** at a configurable ``snapshot_interval`` throughout the
    entire test.  Each snapshot is labelled with the current execution
    phase so that charts show system behaviour *under load* rather than
    at idle phase boundaries.

    Execution flow:

    1. Start background metrics collection.
    2. Start **all** iterations of the wrapped scenario in a background
       thread.
    3. A monitor thread watches runner progress.  When half the
       iterations have started, it **launches** trigger commands on the
       target hosts (non-blocking) and *(optionally)* sleeps for
       ``trigger_wait`` seconds.
    4. The runner thread completes all iterations at a constant rate.
    5. Terminate any trigger commands still running.
    6. *(optional)* Execute **cleanup commands** on the target hosts
       **in parallel**, then sleep for ``cleanup_wait`` seconds.
    7. Stop background metrics collection.
    8. Partition results by trigger timestamp and attach to the Rally
       report.
    """

    def run(
        self,
        scenario_name: str,
        hosts: list[dict[str, Any]] | None = None,
        scenario_args: dict[str, Any] | None = None,
        runner: dict[str, Any] | None = None,
        snapshot_interval: float = 1.0,
        command_timeout: int = 40,
        trigger_wait: float = 0.0,
        cleanup_wait: float = 0.0,
        use_persistent_shell: bool = True,
    ) -> None:
        """Execute the stress-test workload.

        :param scenario_name: Full Rally scenario plugin name, e.g.
            ``"Authenticate.keystone"``.
        :param hosts: A list of host descriptors.  Each element is a
            dict that must contain ``"reach_command"`` — the shell
            command prefix used to execute commands on that host (e.g.
            ``"juju ssh keystone/0 --"`` or
            ``["kubectl", "exec", "pod", "--", "bash", "-c"]``).  Each
            entry may also contain ``"trigger_command"`` (shell command
            to fire at the midpoint), ``"cleanup_command"`` (shell
            command to run after all iterations), ``"label"`` and
            ``"command_timeout"``.
        :param scenario_args: Keyword arguments forwarded to the inner
            scenario's ``run()`` method.
        :param runner: Runner configuration dict, identical in shape to
            the native ``"runner"`` block in a Rally task file.  The
            ``"times"`` field controls the **total** number of
            iterations.  The trigger fires once half of them have
            started.  Defaults to
            ``{"type": "serial", "times": 10}`` when omitted.

            Example — 20 iterations with 4 concurrent workers::

                {"type": "constant", "times": 20, "concurrency": 4}

            Example — 100 iterations at 50 RPS::

                {"type": "rps", "times": 100, "rps": 50}
        :param snapshot_interval: Seconds between consecutive host
            metrics snapshots.  A background thread collects CPU,
            memory and I/O metrics from every target host at this
            interval for the entire duration of the test.  Defaults
            to ``1.0``.
        :param command_timeout: Default timeout in seconds for remote
            command execution (metrics collection).  Trigger and cleanup
            commands use a longer timeout derived from this value.
            Defaults to 40.
        :param trigger_wait: Optional number of seconds to sleep after
            the trigger command(s) are launched.  This gives the
            trigger a head-start (e.g. time for ``stress-ng`` to ramp
            up) while iterations continue uninterrupted.
        :param cleanup_wait: Optional number of seconds to sleep after
            the cleanup command(s) return before collecting the final
            post-cleanup metrics snapshot.
        :param use_persistent_shell: When ``True`` (the default), the
            background metrics collector opens a persistent remote
            shell per host and multiplexes all metric-gathering
            commands through it.  This is fast (sub-second snapshots)
            but can be flaky for long-lived tests.  Set to ``False``
            to spawn a fresh subprocess for every snapshot instead —
            slower (expect 5–10 s intervals) but more robust.
        """
        if not hosts:
            raise ValueError("'hosts' is required.")

        scenario_args = scenario_args or {}
        runner_cfg = dict(runner) if runner else dict(DEFAULT_RUNNER)
        runner_cfg.setdefault("times", 10)

        # Validate early so we fail before host setup.
        scenario.Scenario.get(scenario_name)

        total_times = runner_cfg["times"]
        trigger_at = total_times // 2

        task_obj = self.context["task"]
        inner_context = copy.deepcopy(self.context)

        connections = _build_connections(
            hosts=hosts,
            command_timeout=command_timeout,
        )

        # Determine up-front whether any cleanup command is configured so we
        # can decide whether to run the cleanup phase at all.
        has_cleanup = any(e.cleanup_command for e in connections)

        timer_suffix = " (%d hosts)" % len(connections)

        # -- Build the runner ------------------------------------------------
        step_cfg = dict(runner_cfg)
        step_cfg["times"] = total_times
        runner_cls = ScenarioRunner.get(step_cfg["type"])
        runner_obj = runner_cls(task=task_obj, config=step_cfg)

        # Shared state between the runner thread and the monitor thread.
        trigger_timestamp: float | None = None
        async_handles: list[_AsyncHandle] = []
        trigger_error: list[Exception] = []

        def _monitor_and_trigger() -> None:
            """Watch runner progress; fire triggers at the midpoint."""
            nonlocal trigger_timestamp
            try:
                while not runner_done.is_set():
                    if len(runner_obj.event_queue) >= trigger_at:
                        collector.set_phase("trigger")
                        trigger_timestamp = time.time()
                        async_handles.extend(
                            _start_triggers_async(connections),
                        )
                        if trigger_wait > 0:
                            time.sleep(trigger_wait)
                        collector.set_phase("post_trigger")
                        return
                    # Poll at a short interval to react quickly.
                    runner_done.wait(0.05)
            except Exception as exc:
                logger.error("Trigger monitor failed: %s", exc, exc_info=True)
                trigger_error.append(exc)

        runner_done = threading.Event()

        def _run_scenario() -> None:
            try:
                runner_obj.run(scenario_name, inner_context, scenario_args)
            finally:
                runner_done.set()

        # -- Background metrics collection -----------------------------------
        collector = _SnapshotCollector(
            connections,
            snapshot_interval,
            use_persistent_shell,
        )
        collector.set_phase("pre_trigger")

        with collector:
            # -- 1. Run all iterations with midpoint trigger -----------------
            with atomic.ActionTimer(self, "osstress.iterations"):
                runner_thread = threading.Thread(
                    target=_run_scenario,
                    name="scenario-runner",
                )
                monitor_thread = threading.Thread(
                    target=_monitor_and_trigger,
                    name="trigger-monitor",
                    daemon=True,
                )

                runner_thread.start()
                monitor_thread.start()

                runner_thread.join()
                monitor_thread.join()

            # -- 2. Collect results and terminate triggers -------------------
            all_results = collect_runner_results(runner_obj)

            with atomic.ActionTimer(self, "osstress.trigger_collect" + timer_suffix):
                trigger_infos = _collect_trigger_results(async_handles)

        # -- 3. Cleanup command(s) ------------------------------------------
        cleanup_infos: list[CommandResult] = []
        if has_cleanup:
            cleanup_infos = _cleanup_all(connections)

            if cleanup_wait > 0:
                time.sleep(cleanup_wait)

        # collector thread is now joined — safe to read snapshots
        host_snapshots = collector.snapshots

        # -- 4. Split results by trigger timestamp --------------------------
        if trigger_timestamp is not None:
            first_results = [
                r for r in all_results if r["timestamp"] < trigger_timestamp
            ]
            second_results = [
                r for r in all_results if r["timestamp"] >= trigger_timestamp
            ]
        else:
            # Trigger never fired (e.g. too few iterations).
            logger.warning(
                "Trigger did not fire — all %d results are attributed "
                "to the first half",
                len(all_results),
            )
            first_results = all_results
            second_results = []

        if trigger_error:
            logger.warning(
                "Trigger monitor encountered an error: %s",
                trigger_error[0],
            )

        # -- 5. Attach output data to Rally report --------------------------
        self._emit_output(
            host_snapshots=host_snapshots,
            first_results=first_results,
            second_results=second_results,
            trigger_infos=trigger_infos,
            cleanup_infos=cleanup_infos,
            scenario_name=scenario_name,
        )

    # -------------------------------------------------------------------
    # Output helpers – shared
    # -------------------------------------------------------------------

    def _emit_iteration_charts(
        self,
        first_results: list[dict[str, Any]],
        second_results: list[dict[str, Any]],
        scenario_name: str,
    ) -> None:
        """Emit the iteration-duration and outcome charts (host-independent)."""

        # --- Iteration duration comparison (first half vs second half) ---
        first_durations = [r["duration"] for r in first_results]
        second_durations = [r["duration"] for r in second_results]

        duration_series: list[list[Any]] = []
        if first_durations:
            duration_series.append(
                [
                    "First Half",
                    [[i, d] for i, d in enumerate(first_durations)],
                ]
            )
        if second_durations:
            offset = len(first_durations)
            duration_series.append(
                [
                    "Second Half",
                    [[offset + i, d] for i, d in enumerate(second_durations)],
                ]
            )
        if duration_series:
            self.add_output(
                complete={
                    "title": f"Iteration Durations – {scenario_name}",
                    "description": (
                        "Per-iteration duration (seconds) for the first and "
                        "second halves of the workload"
                    ),
                    "chart_plugin": "Lines",
                    "data": duration_series,
                    "label": "Duration (s)",
                    "axis_label": "Iteration",
                }
            )

        # --- Additive summary pie ---
        first_failures = sum(1 for r in first_results if r["error"])
        second_failures = sum(1 for r in second_results if r["error"])
        first_ok = len(first_results) - first_failures
        second_ok = len(second_results) - second_failures

        self.add_output(
            additive={
                "title": "Iteration Outcome Summary",
                "description": "Successes and failures before/after the trigger",
                "chart_plugin": "Pie",
                "data": [
                    ["First Half OK", first_ok],
                    ["First Half Fail", first_failures],
                    ["Second Half OK", second_ok],
                    ["Second Half Fail", second_failures],
                ],
            }
        )

    def _emit_command_table(
        self,
        infos: list[CommandResult],
        title: str,
        description: str,
    ) -> None:
        """Emit a table with details of commands executed on hosts."""
        if not infos:
            return

        cols = ["Property", "Value"]
        rows: list[list[str]] = []
        for info in infos:
            host_prefix = f"[{info.host}] "
            rows.append([host_prefix + "Command", info.command])
            rows.append([host_prefix + "Return Code", str(info.returncode)])
            rows.append([host_prefix + "Duration (s)", str(info.duration)])
            rows.append(
                [host_prefix + "stdout (truncated)", info.stdout[:512] or "(empty)"]
            )
            rows.append(
                [host_prefix + "stderr (truncated)", info.stderr[:512] or "(empty)"]
            )

        self.add_output(
            complete={
                "title": title,
                "description": description,
                "chart_plugin": "Table",
                "data": {"cols": cols, "rows": rows},
            }
        )

    # -------------------------------------------------------------------
    # Output helpers – multi-host (HA)
    # -------------------------------------------------------------------

    def _emit_output(
        self,
        host_snapshots: dict[str, list],
        first_results: list[dict[str, Any]],
        second_results: list[dict[str, Any]],
        trigger_infos: list[CommandResult],
        cleanup_infos: list[CommandResult],
        scenario_name: str,
    ) -> None:
        """Attach all collected data to the Rally report (multi-host)."""

        host_labels = sorted(host_snapshots.keys())

        # --- Per-host comparison charts (memory / cpu / io) ---
        for chart in build_rally_output_charts(host_snapshots):
            self.add_output(complete=chart)

        # --- Iteration charts (host-independent) ---
        self._emit_iteration_charts(first_results, second_results, scenario_name)

        # --- Trigger table (one block per host) ---
        self._emit_command_table(
            trigger_infos,
            title="Trigger Command Details",
            description="Details of the trigger command(s) executed between the two halves",
        )

        # --- Cleanup table (one block per host) ---
        self._emit_command_table(
            cleanup_infos,
            title="Cleanup Command Details",
            description="Details of the cleanup command(s) executed after all iterations",
        )

        # --- CPU usage deltas table — all hosts combined ---
        cpu_rows: list[list[str]] = []
        for hlabel in host_labels:
            snaps = host_snapshots[hlabel]
            for i in range(1, len(snaps)):
                b = snaps[i - 1].cpu
                a = snaps[i].cpu
                if b and a:
                    usage = b.usage_pct(a)
                    cpu_rows.append(
                        [
                            hlabel,
                            f"{snaps[i - 1].label} -> {snaps[i].label}",
                            f"{usage['user_pct']}%",
                            f"{usage['system_pct']}%",
                            f"{usage['iowait_pct']}%",
                            f"{usage['idle_pct']}%",
                            f"{usage['busy_pct']}%",
                        ]
                    )
        if cpu_rows:
            self.add_output(
                complete={
                    "title": "Host CPU Usage Between Samples — All Hosts",
                    "description": "CPU time breakdown between consecutive snapshots per host",
                    "chart_plugin": "Table",
                    "data": {
                        "cols": [
                            "Host",
                            "Interval",
                            "User %",
                            "System %",
                            "IOWait %",
                            "Idle %",
                            "Busy %",
                        ],
                        "rows": cpu_rows,
                    },
                }
            )

        # --- I/O deltas table — all hosts combined ---
        io_rows: list[list[str]] = []
        for hlabel in host_labels:
            snaps = host_snapshots[hlabel]
            for i in range(1, len(snaps)):
                b = snaps[i - 1].io
                a = snaps[i].io
                if b and a:
                    delta = b.diff(a)
                    io_rows.append(
                        [
                            hlabel,
                            f"{snaps[i - 1].label} -> {snaps[i].label}",
                            str(delta["reads_completed"]),
                            str(delta["sectors_read"]),
                            str(delta["ms_reading"]),
                            str(delta["writes_completed"]),
                            str(delta["sectors_written"]),
                            str(delta["ms_writing"]),
                            str(delta["ms_doing_io"]),
                        ]
                    )
        if io_rows:
            self.add_output(
                complete={
                    "title": "Host Disk I/O Between Samples — All Hosts",
                    "description": "Cumulative I/O counter deltas between snapshots per host",
                    "chart_plugin": "Table",
                    "data": {
                        "cols": [
                            "Host",
                            "Interval",
                            "Reads",
                            "Sectors Read",
                            "ms Reading",
                            "Writes",
                            "Sectors Written",
                            "ms Writing",
                            "ms Doing I/O",
                        ],
                        "rows": io_rows,
                    },
                }
            )
