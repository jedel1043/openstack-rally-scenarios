"""OsStress Rally scenario plugin — split-run stress testing.

Moved from the top-level ``scenario.py`` into the ``plugins`` sub-package.

Each half of the split run delegates to a real Rally runner instance
(``serial``, ``constant``, ``rps``, …) so you get the runner's full
feature set (concurrency, RPS throttling, timeouts, …) for free.

Host metrics (CPU, memory, I/O) are collected in a **background thread**
at a configurable ``snapshot_interval`` so that snapshots reflect the
system state while it is actually under load, not just at idle phase
boundaries.
"""

from __future__ import annotations

import copy
import logging
import shlex
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from rally.task import atomic, scenario, validation

from rally_openstack.task import scenario as os_scenario

from common import DEFAULT_RUNNER, run_via_runner

from metrics import (
    HostConnection,
    build_rally_output_charts,
    build_rally_output_charts_multi,
    build_ssh_reach_command,
    collect_snapshot,
    cpu_usage_pct,
    io_diff,
    snapshot_to_dict,
)

LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _remote_trigger(
    conn: HostConnection,
    command: str,
) -> dict[str, Any]:
    """Execute *command* on the remote host and return execution details.

    Uses the transport-agnostic *reach_command* stored in *conn*.  This
    works for plain SSH, ``juju ssh``, ``kubectl exec``, or any other
    command prefix that accepts a shell command as a trailing argument.
    """
    cmd = list(conn.reach_command) + [command]
    LOG.info(
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

    info: dict[str, Any] = {
        "host": conn.label,
        "command": command,
        "returncode": result.returncode,
        "duration": round(elapsed, 4),
        "stdout": result.stdout[:4096],
        "stderr": result.stderr[:4096],
    }
    if result.returncode != 0:
        LOG.warning(
            "Remote command on %s exited %d – stderr: %s",
            conn.label,
            result.returncode,
            result.stderr.strip()[:512],
        )
    return info


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
    should keep running while the second half of iterations executes.
    """
    cmd = list(conn.reach_command) + [command]
    LOG.info(
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
) -> list[dict[str, Any]]:
    """Terminate every async trigger and return result-info dicts.

    *handles* is a list of opaque handles returned by
    :func:`_remote_trigger_async`.  Each process that is still running
    is terminated immediately so the scenario can proceed to cleanup.
    """
    infos: list[dict[str, Any]] = []
    for label, command, proc, t0 in handles:
        if proc.poll() is None:
            LOG.info("Terminating background trigger on %s", label)
            proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
        else:
            stdout, stderr = proc.communicate()
        elapsed = time.monotonic() - t0
        info: dict[str, Any] = {
            "host": label,
            "command": command,
            "returncode": proc.returncode if proc.returncode is not None else -1,
            "duration": round(elapsed, 4),
            "stdout": (stdout or "")[:4096],
            "stderr": (stderr or "")[:4096],
        }
        if proc.returncode and proc.returncode != 0:
            LOG.warning(
                "Background trigger on %s exited %d – stderr: %s",
                label,
                proc.returncode,
                (stderr or "").strip()[:512],
            )
        infos.append(info)
    return infos


# The connection tuple used throughout this module:
#   (label, HostConnection, trigger_command, cleanup_command)
_ConnTuple = tuple[str, HostConnection, str, str]


def _host_conn_from_ssh_params(
    host: str,
    username: str = "ubuntu",
    port: int = 22,
    key_file: str | None = None,
    connect_timeout: int = 10,
) -> HostConnection:
    """Build a :class:`HostConnection` from traditional SSH parameters."""
    return HostConnection(
        label=host,
        reach_command=build_ssh_reach_command(
            host=host,
            username=username,
            port=port,
            key_file=key_file,
            connect_timeout=connect_timeout,
        ),
        command_timeout=connect_timeout + 30,
    )


def _parse_reach_command(raw: str | list[str]) -> list[str]:
    """Normalise a *reach_command* value to a list of strings."""
    if isinstance(raw, str):
        return shlex.split(raw)
    return list(raw)


def _build_connections(
    hosts: list[dict[str, Any]] | None,
    host: str | None,
    reach_command: str | list[str] | None,
    trigger_command: str,
    cleanup_command: str,
    username: str,
    port: int,
    key_file: str | None,
    connect_timeout: int,
    command_timeout: int,
) -> list[_ConnTuple]:
    """Normalise the single-host and multi-host arguments.

    Returns a list of ``(label, HostConnection, trigger_command,
    cleanup_command)`` tuples.

    Each host can be specified either by SSH parameters (``host``,
    ``username``, ``port``, ``key_file``, ``connect_timeout``) **or** by
    an explicit ``reach_command`` — the shell command prefix used to
    execute commands on that host (e.g. ``"juju ssh keystone/0 --"`` or
    ``["kubectl", "exec", "pod", "--", "bash", "-c"]``).

    In multi-host mode each entry in *hosts* can override any of the
    top-level defaults and can carry its own ``trigger_command`` and
    ``cleanup_command``.  Entries that omit either command inherit the
    corresponding top-level value.  An entry may also set a command to
    ``null`` / empty string to explicitly skip it on that host (metrics
    are still collected).
    """
    if hosts:
        conns: list[_ConnTuple] = []
        for idx, entry in enumerate(hosts):
            h = entry.get("host")
            rc = entry.get("reach_command")

            if h and rc:
                raise ValueError(
                    f"hosts[{idx}] specifies both 'host' and "
                    f"'reach_command'; use one or the other"
                )

            if rc:
                rc_list = _parse_reach_command(rc)
                label = entry.get("label", rc if isinstance(rc, str) else " ".join(rc))
                ct = entry.get("command_timeout", command_timeout)
                conn = HostConnection(
                    label=label,
                    reach_command=rc_list,
                    command_timeout=ct,
                )
            elif h:
                label = entry.get("label", h)
                conn = _host_conn_from_ssh_params(
                    host=h,
                    username=entry.get("username", username),
                    port=entry.get("port", port),
                    key_file=entry.get("key_file", key_file),
                    connect_timeout=entry.get("connect_timeout", connect_timeout),
                )
            else:
                raise ValueError(
                    f"hosts[{idx}] must contain either 'host' or "
                    f"'reach_command'"
                )

            trig = entry.get("trigger_command", trigger_command)
            clean = entry.get("cleanup_command", cleanup_command)
            conns.append((label, conn, trig, clean))
        return conns

    # --- Single-host mode ---------------------------------------------------
    if host and reach_command:
        raise ValueError(
            "Specify either 'host' (SSH mode) or 'reach_command' "
            "(custom transport), not both."
        )

    if reach_command:
        rc_list = _parse_reach_command(reach_command)
        label = reach_command if isinstance(reach_command, str) else " ".join(reach_command)
        conn = HostConnection(
            label=label,
            reach_command=rc_list,
            command_timeout=command_timeout,
        )
        return [(label, conn, trigger_command, cleanup_command)]

    if host:
        conn = _host_conn_from_ssh_params(
            host=host,
            username=username,
            port=port,
            key_file=key_file,
            connect_timeout=connect_timeout,
        )
        return [(host, conn, trigger_command, cleanup_command)]

    raise ValueError(
        "One of 'host', 'reach_command', or 'hosts' must be provided."
    )


def _collect_all_snapshots(
    connections: list[_ConnTuple],
    sample_label: str,
) -> dict[str, Any]:
    """Collect a metrics snapshot from every host, in parallel.

    Returns ``{host_label: HostMetricsSnapshot}``.
    """
    results: dict[str, Any] = {}
    if len(connections) == 1:
        label, conn, _trig, _clean = connections[0]
        results[label] = collect_snapshot(conn, sample_label)
        return results

    with ThreadPoolExecutor(max_workers=len(connections)) as pool:
        futures = {
            pool.submit(collect_snapshot, conn, sample_label): label
            for label, conn, _trig, _clean in connections
        }
        for fut in as_completed(futures):
            label = futures[fut]
            try:
                results[label] = fut.result()
            except Exception as exc:
                LOG.warning("Metrics collection failed for %s: %s", label, exc)
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
        connections: list[_ConnTuple],
        interval: float,
    ) -> None:
        self._connections = connections
        self._interval = interval
        self._stop = threading.Event()
        self._phase = "idle"
        self._counter = 0
        self._snapshots: dict[str, list] = {
            label: [] for label, _, _, _ in connections
        }
        self._thread: threading.Thread | None = None

    # -- phase control ------------------------------------------------------

    def set_phase(self, phase: str) -> None:
        """Update the phase label applied to subsequent snapshots."""
        self._phase = phase

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="snapshot-collector",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def __enter__(self) -> "_SnapshotCollector":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.stop()
        return False

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
                    self._connections, sample_label,
                )
                for host_label, snap in results.items():
                    self._snapshots[host_label].append(snap)
            except Exception:
                LOG.warning(
                    "Background snapshot #%d failed",
                    self._counter,
                    exc_info=True,
                )
            self._stop.wait(self._interval)


def _run_commands_on_hosts(
    targets: list[tuple[str, HostConnection, str]],
    phase_name: str,
) -> list[dict[str, Any]]:
    """Fire a command on every host in *targets*, in parallel.

    *targets* is a list of ``(label, HostConnection, command)`` triples.
    Entries whose command is empty or ``None`` are silently skipped.
    Returns a list of result-info dicts (one per host that was executed).
    *phase_name* is used only for log messages (e.g. ``"trigger"`` or
    ``"cleanup"``).
    """
    to_run = [
        (label, conn, cmd)
        for label, conn, cmd in targets
        if cmd
    ]
    if not to_run:
        return []

    if len(to_run) == 1:
        _label, conn, cmd = to_run[0]
        return [_remote_trigger(conn, cmd)]

    infos: list[dict[str, Any]] = []
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
                LOG.warning("%s failed for %s: %s", phase_name, label, exc)
                infos.append({
                    "host": label,
                    "command": "(failed)",
                    "returncode": -1,
                    "duration": 0,
                    "stdout": "",
                    "stderr": str(exc),
                })
    return infos


def _start_triggers_async(
    connections: list[_ConnTuple],
) -> list[_AsyncHandle]:
    """Launch trigger commands on all hosts without blocking.

    Returns a list of opaque handles.  Pass them to
    :func:`_collect_trigger_results` after the second half of iterations
    to obtain the result-info dicts.  Connections whose trigger command
    is empty are silently skipped.
    """
    handles: list[_AsyncHandle] = []
    for label, conn, trig, _clean in connections:
        if not trig:
            continue
        handles.append(_remote_trigger_async(conn, trig))
    return handles


def _cleanup_all(
    connections: list[_ConnTuple],
) -> list[dict[str, Any]]:
    """Fire the cleanup command on every host, in parallel."""
    targets = [
        (label, conn, clean)
        for label, conn, _trig, clean in connections
    ]
    return _run_commands_on_hosts(targets, "Cleanup")


# ---------------------------------------------------------------------------
# Rally scenario plugin
# ---------------------------------------------------------------------------


@validation.add("required_platform", platform="openstack", users=True)
@os_scenario.configure(
    name="OsStress.split_run",
    platform="openstack",
)
class SplitRun(os_scenario.OpenStackScenario):
    """Run an OpenStack scenario in two halves with a trigger in between.

    Supports both **single-host** and **multi-host (HA)** modes.

    In single-host mode supply ``host`` (a string).  In multi-host mode
    supply ``hosts`` (a list of dicts).  Each host entry may override any
    top-level SSH default and may carry its own ``trigger_command`` and
    ``cleanup_command``.

    Host metrics (CPU, memory, I/O) are collected in a **background
    thread** at a configurable ``snapshot_interval`` throughout the
    entire test.  Each snapshot is labelled with the current execution
    phase so that charts show system behaviour *under load* rather than
    at idle phase boundaries.

    Execution flow:

    1. Start background metrics collection.
    2. Run the **first half** of iterations of the wrapped scenario.
    3. **Launch** trigger commands on the target hosts (non-blocking).
    4. *(optional)* Sleep for ``trigger_wait`` seconds.
    5. Run the **second half** of iterations **while triggers are still
       running** in the background.
    6. Terminate any trigger commands still running.
    7. *(optional)* Execute **cleanup commands** on the target hosts
       **in parallel**, then sleep for ``cleanup_wait`` seconds.
    8. Stop background metrics collection.
    9. Attach all metrics and results to the Rally report.
    """

    def run(
        self,
        scenario_name: str,
        trigger_command: str | None = None,
        host: str | None = None,
        hosts: list[dict[str, Any]] | None = None,
        reach_command: str | list[str] | None = None,
        scenario_args: dict[str, Any] | None = None,
        runner: dict[str, Any] | None = None,
        snapshot_interval: float = 5.0,
        username: str = "ubuntu",
        port: int = 22,
        key_file: str | None = None,
        connect_timeout: int = 10,
        command_timeout: int = 40,
        trigger_wait: float = 0.0,

        cleanup_command: str = "",
        cleanup_wait: float = 0.0,
    ) -> None:
        """Execute the stress-test workload.

        :param scenario_name: Full Rally scenario plugin name, e.g.
            ``"Authenticate.keystone"``.
        :param trigger_command: Default shell command to execute on the
            target host(s) between the two halves of the run.  In
            multi-host mode individual entries in ``hosts`` may override
            this value.
        :param host: IP address or hostname of a **single** machine to
            reach via SSH for metrics collection and trigger execution.
            Mutually exclusive with ``hosts`` and ``reach_command``.
        :param hosts: A list of host descriptors for **multi-host (HA)**
            mode.  Each element is a dict that **must** contain ``"host"``
            and may optionally contain ``"label"``,
            ``"trigger_command"``, ``"cleanup_command"``, ``"username"``,
            ``"port"``, ``"key_file"`` and ``"connect_timeout"`` to
            override the top-level defaults.  Mutually exclusive with
            ``host``.
        :param reach_command: Shell command (string) or command list used
            to reach a **single** target host.  The remote command to
            execute is appended as a trailing argument.  Examples:
            ``"juju ssh keystone/0 --"`` or
            ``["kubectl", "exec", "pod", "--", "bash", "-c"]``.
            Mutually exclusive with ``host``.  When using ``hosts``
            (multi-host mode) each entry may carry its own
            ``reach_command`` instead of ``host``.
        :param scenario_args: Keyword arguments forwarded to the inner
            scenario's ``run()`` method.
        :param runner: Runner configuration dict, identical in shape to
            the native ``"runner"`` block in a Rally task file.  The
            ``"times"`` field controls the **total** number of
            iterations (split roughly in half).  Defaults to
            ``{"type": "serial", "times": 10}`` when omitted.

            Example — 20 iterations with 4 concurrent workers::

                {"type": "constant", "times": 20, "concurrency": 4}

            Example — 100 iterations at 50 RPS::

                {"type": "rps", "times": 100, "rps": 50}
        :param snapshot_interval: Seconds between consecutive host
            metrics snapshots.  A background thread collects CPU,
            memory and I/O metrics from every target host at this
            interval for the entire duration of the test.  Defaults
            to ``5.0``.
        :param username: Default SSH username for the target host(s).
        :param port: Default SSH port for the target host(s).
        :param key_file: Default path to the SSH private key.  ``None``
            means the system default key will be used.
        :param connect_timeout: Default SSH connection timeout in seconds.
        :param command_timeout: Default timeout in seconds for remote
            command execution (metrics collection).  Trigger and cleanup
            commands use a longer timeout derived from this value.
            Defaults to 40.  Ignored when ``host`` is used (derived
            from ``connect_timeout`` instead).
        :param trigger_wait: Optional number of seconds to sleep after
            the trigger command(s) are launched before starting the
            second half.  This gives the trigger a head-start (e.g.
            time for ``stress-ng`` to ramp up) before requests begin.
        :param cleanup_command: Default shell command to execute on the
            target host(s) **after all iterations have completed**, to
            restore the state changed by ``trigger_command`` (e.g.
            ``"sudo systemctl start keystone"`` to undo a preceding
            ``"sudo systemctl stop keystone"``).  In multi-host mode
            individual ``hosts`` entries may override this.  Leave empty
            to skip the cleanup phase.
        :param cleanup_wait: Optional number of seconds to sleep after
            the cleanup command(s) return before collecting the final
            post-cleanup metrics snapshot.
        """
        exclusive = sum(1 for x in (host, hosts, reach_command) if x)
        if exclusive > 1 and not hosts:
            raise ValueError(
                "Specify exactly one of 'host' (SSH single-host), "
                "'reach_command' (custom single-host), or 'hosts' "
                "(multi-host mode)."
            )
        if host and hosts:
            raise ValueError(
                "Specify either 'host'/'reach_command' (single-host mode) "
                "or 'hosts' (multi-host mode), not both."
            )
        if reach_command and hosts:
            raise ValueError(
                "Top-level 'reach_command' is for single-host mode.  "
                "In multi-host mode, set 'reach_command' inside each "
                "entry in 'hosts'."
            )

        scenario_args = scenario_args or {}
        runner_cfg = dict(runner) if runner else dict(DEFAULT_RUNNER)
        runner_cfg.setdefault("times", 10)

        # Validate early so we fail before host setup.
        scenario.Scenario.get(scenario_name)

        total_times = runner_cfg["times"]
        first_half = total_times // 2
        second_half = total_times - first_half

        task_obj = self.context["task"]
        inner_context = copy.deepcopy(self.context)

        connections = _build_connections(
            hosts=hosts,
            host=host,
            reach_command=reach_command,
            trigger_command=trigger_command,
            cleanup_command=cleanup_command,
            username=username,
            port=port,
            key_file=key_file,
            connect_timeout=connect_timeout,
            command_timeout=command_timeout,
        )
        multi = len(connections) > 1

        # Determine up-front whether any cleanup command is configured so we
        # can decide whether to run the cleanup phase at all.
        has_cleanup = any(clean for _, _, _, clean in connections)

        timer_suffix = " (%d hosts)" % len(connections) if multi else ""

        # -- Background metrics collection --------------------------------------
        # A background thread takes snapshots at ``snapshot_interval`` for
        # the entire test, so we capture system state *under load* rather
        # than at idle phase boundaries.
        collector = _SnapshotCollector(connections, snapshot_interval)
        collector.set_phase("warmup")

        with collector:
            # -- 1. First half of iterations ------------------------------------
            with atomic.ActionTimer(self, "osstress.warmup"):
                first_results = run_via_runner(
                    scenario_name=scenario_name,
                    scenario_args=scenario_args,
                    runner_cfg=runner_cfg,
                    times=first_half,
                    task=task_obj,
                    context=inner_context,
                )

            # -- 2. Trigger command(s) ------------------------------------------
            # Triggers are launched asynchronously so that long-lived
            # commands (e.g. stress-ng) keep running alongside the
            # second half of iterations.
            collector.set_phase("trigger")
            with atomic.ActionTimer(self, "osstress.trigger_commands" + timer_suffix):
                async_handles = _start_triggers_async(connections)

            if trigger_wait > 0:
                collector.set_phase("post_trigger_settle")
                time.sleep(trigger_wait)

            # -- 3. Second half (triggers still running) --------------------
            collector.set_phase("post_trigger")
            with atomic.ActionTimer(self, "osstress.post_trigger"):
                second_results = run_via_runner(
                    scenario_name=scenario_name,
                    scenario_args=scenario_args,
                    runner_cfg=runner_cfg,
                    times=second_half,
                    task=task_obj,
                    context=inner_context,
                )

            # Terminate any triggers still running now that the
            # second half is done.
            trigger_infos = _collect_trigger_results(async_handles)

        # -- 4. Cleanup command(s) ------------------------------------------
        cleanup_infos: list[dict[str, Any]] = []
        if has_cleanup:
            cleanup_infos = _cleanup_all(connections)

            if cleanup_wait > 0:
                time.sleep(cleanup_wait)

        # collector thread is now joined — safe to read snapshots
        host_snapshots = collector.snapshots

        # -- 5. Attach output data to Rally report ------------------------------
        if multi:
            self._emit_output_multi(
                host_snapshots=host_snapshots,
                first_results=first_results,
                second_results=second_results,
                trigger_infos=trigger_infos,
                cleanup_infos=cleanup_infos,
                scenario_name=scenario_name,
            )
        else:
            # Single-host path — flatten into a plain list for the
            # original charting function.
            label = next(iter(host_snapshots))
            self._emit_output_single(
                snapshots=host_snapshots[label],
                first_results=first_results,
                second_results=second_results,
                trigger_infos=trigger_infos,
                cleanup_infos=cleanup_infos,
                scenario_name=scenario_name,
                host_label=label,
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
            duration_series.append([
                "First Half",
                [[i, d] for i, d in enumerate(first_durations)],
            ])
        if second_durations:
            offset = len(first_durations)
            duration_series.append([
                "Second Half",
                [[offset + i, d] for i, d in enumerate(second_durations)],
            ])
        if duration_series:
            self.add_output(complete={
                "title": f"Iteration Durations – {scenario_name}",
                "description": (
                    "Per-iteration duration (seconds) for the first and "
                    "second halves of the workload"
                ),
                "chart_plugin": "Lines",
                "data": duration_series,
                "label": "Duration (s)",
                "axis_label": "Iteration",
            })

        # --- Additive summary pie ---
        first_failures = sum(1 for r in first_results if r["error"])
        second_failures = sum(1 for r in second_results if r["error"])
        first_ok = len(first_results) - first_failures
        second_ok = len(second_results) - second_failures

        self.add_output(additive={
            "title": "Iteration Outcome Summary",
            "description": "Successes and failures before/after the trigger",
            "chart_plugin": "Pie",
            "data": [
                ["First Half OK", first_ok],
                ["First Half Fail", first_failures],
                ["Second Half OK", second_ok],
                ["Second Half Fail", second_failures],
            ],
        })

    def _emit_command_table(
        self,
        infos: list[dict[str, Any]],
        multi: bool,
        title: str,
        description: str,
    ) -> None:
        """Emit a table with details of commands executed on hosts.

        Used for both the trigger-command and cleanup-command tables.
        """
        if not infos:
            return

        cols = ["Property", "Value"]
        if multi:
            rows: list[list[str]] = []
            for info in infos:
                host_prefix = f"[{info.get('host', '?')}] "
                rows.append([host_prefix + "Command", info["command"]])
                rows.append([host_prefix + "Return Code", str(info["returncode"])])
                rows.append([host_prefix + "Duration (s)", str(info["duration"])])
                rows.append([host_prefix + "stdout (truncated)", info["stdout"][:512] or "(empty)"])
                rows.append([host_prefix + "stderr (truncated)", info["stderr"][:512] or "(empty)"])
        else:
            info = infos[0]
            rows = [
                ["Command", info["command"]],
                ["Return Code", str(info["returncode"])],
                ["Duration (s)", str(info["duration"])],
                ["stdout (truncated)", info["stdout"][:512] or "(empty)"],
                ["stderr (truncated)", info["stderr"][:512] or "(empty)"],
            ]

        self.add_output(complete={
            "title": title,
            "description": description,
            "chart_plugin": "Table",
            "data": {"cols": cols, "rows": rows},
        })

    # -------------------------------------------------------------------
    # Output helpers – single-host
    # -------------------------------------------------------------------

    def _emit_output_single(
        self,
        snapshots: list,
        first_results: list[dict[str, Any]],
        second_results: list[dict[str, Any]],
        trigger_infos: list[dict[str, Any]],
        cleanup_infos: list[dict[str, Any]],
        scenario_name: str,
        host_label: str,
    ) -> None:
        """Attach all collected data to the Rally report (single-host)."""

        # --- Host metric charts (memory / cpu / io) ---
        for chart in build_rally_output_charts(snapshots):
            self.add_output(complete=chart)

        # --- Iteration charts ---
        self._emit_iteration_charts(first_results, second_results, scenario_name)

        # --- Trigger table ---
        self._emit_command_table(
            trigger_infos,
            multi=False,
            title="Trigger Command Details",
            description="Details of the command(s) executed between the two halves",
        )

        # --- Cleanup table ---
        self._emit_command_table(
            cleanup_infos,
            multi=False,
            title="Cleanup Command Details",
            description="Details of the cleanup command(s) executed after all iterations",
        )

        # --- Detailed host metrics table ---
        snapshot_rows: list[list[str]] = []
        for snap_dict in [snapshot_to_dict(s) for s in snapshots]:
            mem = snap_dict.get("memory", {})
            io_data = snap_dict.get("io", {})
            snapshot_rows.append([
                snap_dict["label"],
                f"{mem.get('mem_used_pct', 'N/A')}%",
                str(mem.get("mem_used_kb", "N/A")),
                str(mem.get("mem_total_kb", "N/A")),
                str(io_data.get("reads_completed", "N/A")),
                str(io_data.get("writes_completed", "N/A")),
                str(io_data.get("ios_in_progress", "N/A")),
            ])

        if snapshot_rows:
            self.add_output(complete={
                "title": f"Host Metrics – Raw Snapshots ({host_label})",
                "description": (
                    "Point-in-time resource usage captured from the service host"
                ),
                "chart_plugin": "Table",
                "data": {
                    "cols": [
                        "Sample",
                        "Mem Used %",
                        "Mem Used (kB)",
                        "Mem Total (kB)",
                        "Disk Reads",
                        "Disk Writes",
                        "IOs In-Flight",
                    ],
                    "rows": snapshot_rows,
                },
            })

        # --- CPU usage deltas table ---
        cpu_rows: list[list[str]] = []
        for i in range(1, len(snapshots)):
            b = snapshots[i - 1].cpu
            a = snapshots[i].cpu
            if b and a:
                usage = cpu_usage_pct(b, a)
                cpu_rows.append([
                    f"{snapshots[i - 1].label} -> {snapshots[i].label}",
                    f"{usage['user_pct']}%",
                    f"{usage['system_pct']}%",
                    f"{usage['iowait_pct']}%",
                    f"{usage['idle_pct']}%",
                    f"{usage['busy_pct']}%",
                ])
        if cpu_rows:
            self.add_output(complete={
                "title": f"Host CPU Usage Between Samples ({host_label})",
                "description": "CPU time breakdown between consecutive snapshots",
                "chart_plugin": "Table",
                "data": {
                    "cols": [
                        "Interval",
                        "User %",
                        "System %",
                        "IOWait %",
                        "Idle %",
                        "Busy %",
                    ],
                    "rows": cpu_rows,
                },
            })

        # --- I/O deltas table ---
        io_rows: list[list[str]] = []
        for i in range(1, len(snapshots)):
            b = snapshots[i - 1].io
            a = snapshots[i].io
            if b and a:
                delta = io_diff(b, a)
                io_rows.append([
                    f"{snapshots[i - 1].label} -> {snapshots[i].label}",
                    str(delta["reads_completed"]),
                    str(delta["sectors_read"]),
                    str(delta["ms_reading"]),
                    str(delta["writes_completed"]),
                    str(delta["sectors_written"]),
                    str(delta["ms_writing"]),
                    str(delta["ms_doing_io"]),
                ])
        if io_rows:
            self.add_output(complete={
                "title": f"Host Disk I/O Between Samples ({host_label})",
                "description": "Cumulative I/O counter deltas between snapshots",
                "chart_plugin": "Table",
                "data": {
                    "cols": [
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
            })

    # -------------------------------------------------------------------
    # Output helpers – multi-host (HA)
    # -------------------------------------------------------------------

    def _emit_output_multi(
        self,
        host_snapshots: dict[str, list],
        first_results: list[dict[str, Any]],
        second_results: list[dict[str, Any]],
        trigger_infos: list[dict[str, Any]],
        cleanup_infos: list[dict[str, Any]],
        scenario_name: str,
    ) -> None:
        """Attach all collected data to the Rally report (multi-host)."""

        host_labels = sorted(host_snapshots.keys())

        # --- Per-host comparison charts (memory / cpu / io) ---
        for chart in build_rally_output_charts_multi(host_snapshots):
            self.add_output(complete=chart)

        # --- Iteration charts (host-independent) ---
        self._emit_iteration_charts(first_results, second_results, scenario_name)

        # --- Trigger table (one block per host) ---
        self._emit_command_table(
            trigger_infos,
            multi=True,
            title="Trigger Command Details",
            description="Details of the trigger command(s) executed between the two halves",
        )

        # --- Cleanup table (one block per host) ---
        self._emit_command_table(
            cleanup_infos,
            multi=True,
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
                    usage = cpu_usage_pct(b, a)
                    cpu_rows.append([
                        hlabel,
                        f"{snaps[i - 1].label} -> {snaps[i].label}",
                        f"{usage['user_pct']}%",
                        f"{usage['system_pct']}%",
                        f"{usage['iowait_pct']}%",
                        f"{usage['idle_pct']}%",
                        f"{usage['busy_pct']}%",
                    ])
        if cpu_rows:
            self.add_output(complete={
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
            })

        # --- I/O deltas table — all hosts combined ---
        io_rows: list[list[str]] = []
        for hlabel in host_labels:
            snaps = host_snapshots[hlabel]
            for i in range(1, len(snaps)):
                b = snaps[i - 1].io
                a = snaps[i].io
                if b and a:
                    delta = io_diff(b, a)
                    io_rows.append([
                        hlabel,
                        f"{snaps[i - 1].label} -> {snaps[i].label}",
                        str(delta["reads_completed"]),
                        str(delta["sectors_read"]),
                        str(delta["ms_reading"]),
                        str(delta["writes_completed"]),
                        str(delta["sectors_written"]),
                        str(delta["ms_writing"]),
                        str(delta["ms_doing_io"]),
                    ])
        if io_rows:
            self.add_output(complete={
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
            })