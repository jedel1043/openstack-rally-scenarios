"""Transport-agnostic host metrics collector for CPU, memory and I/O."""

from __future__ import annotations

import logging
import shlex
import subprocess
import time

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Remote-execution helpers
# ---------------------------------------------------------------------------

# Commands executed on the remote host to gather metrics.
# Each returns a single parseable blob on stdout.
_CMD_CPU = r"grep -E '^cpu ' /proc/stat"
_CMD_MEMORY = "cat /proc/meminfo"
_CMD_IO = "cat /proc/diskstats"


def build_ssh_reach_command(
    host,  # type: str
    username="ubuntu",  # type: str
    port=22,  # type: int
    key_file=None,  # type: Optional[str]
    connect_timeout=10,  # type: int
):
    # type: (...) -> List[str]
    """Build an SSH *reach_command* prefix from traditional SSH parameters.

    The returned list can be passed as the *reach_command* argument to
    :class:`HostConnection`.  When combined with a remote command string
    it produces a complete ``ssh`` invocation::

        reach = build_ssh_reach_command("10.0.0.1")
        subprocess.run(reach + ["cat /etc/hostname"])
    """
    cmd = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=%d" % connect_timeout,
        "-p",
        str(port),
    ]
    if key_file:
        cmd += ["-i", key_file]
    cmd.append("%s@%s" % (username, host))
    return cmd


def _exec_remote(
    conn,  # type: HostConnection
    remote_cmd,  # type: str
):
    # type: (...) -> str
    """Execute *remote_cmd* on the host described by *conn* and return stdout.

    The full command executed locally is ``conn.reach_command + [remote_cmd]``.
    This works for any transport — SSH, ``juju ssh``, ``kubectl exec``, etc.
    """
    cmd = list(conn.reach_command) + [remote_cmd]
    _logger.debug(
        "Remote exec on %s: %s", conn.label, " ".join(shlex.quote(c) for c in cmd)
    )
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=conn.command_timeout,
    )
    if result.returncode != 0:
        _logger.warning(
            "Remote command failed on %s (rc=%d): %s\nstderr: %s",
            conn.label,
            result.returncode,
            remote_cmd,
            result.stderr.strip(),
        )
    return result.stdout


# ---------------------------------------------------------------------------
# Metric snapshot classes  (plain classes – no dataclasses)
# ---------------------------------------------------------------------------


class CpuSnapshot(object):
    """Raw counters from ``/proc/stat`` (first ``cpu`` line)."""

    __slots__ = (
        "user",
        "nice",
        "system",
        "idle",
        "iowait",
        "irq",
        "softirq",
        "steal",
        "timestamp",
    )

    def __init__(
        self,
        user,  # type: int
        nice,  # type: int
        system,  # type: int
        idle,  # type: int
        iowait,  # type: int
        irq,  # type: int
        softirq,  # type: int
        steal,  # type: int
        timestamp,  # type: float
    ):
        self.user = user
        self.nice = nice
        self.system = system
        self.idle = idle
        self.iowait = iowait
        self.irq = irq
        self.softirq = softirq
        self.steal = steal
        self.timestamp = timestamp

    @property
    def total(self):
        # type: () -> int
        return (
            self.user
            + self.nice
            + self.system
            + self.idle
            + self.iowait
            + self.irq
            + self.softirq
            + self.steal
        )

    @property
    def busy(self):
        # type: () -> int
        return self.total - self.idle - self.iowait

    def to_dict(self):
        # type: () -> Dict[str, Any]
        return {
            "user": self.user,
            "nice": self.nice,
            "system": self.system,
            "idle": self.idle,
            "iowait": self.iowait,
            "irq": self.irq,
            "softirq": self.softirq,
            "steal": self.steal,
            "timestamp": self.timestamp,
        }


class MemorySnapshot(object):
    """Parsed subset of ``/proc/meminfo`` (values in kB)."""

    __slots__ = (
        "mem_total_kb",
        "mem_free_kb",
        "mem_available_kb",
        "buffers_kb",
        "cached_kb",
        "swap_total_kb",
        "swap_free_kb",
        "timestamp",
    )

    def __init__(
        self,
        mem_total_kb,  # type: int
        mem_free_kb,  # type: int
        mem_available_kb,  # type: int
        buffers_kb,  # type: int
        cached_kb,  # type: int
        swap_total_kb,  # type: int
        swap_free_kb,  # type: int
        timestamp,  # type: float
    ):
        self.mem_total_kb = mem_total_kb
        self.mem_free_kb = mem_free_kb
        self.mem_available_kb = mem_available_kb
        self.buffers_kb = buffers_kb
        self.cached_kb = cached_kb
        self.swap_total_kb = swap_total_kb
        self.swap_free_kb = swap_free_kb
        self.timestamp = timestamp

    @property
    def mem_used_kb(self):
        # type: () -> int
        return self.mem_total_kb - self.mem_available_kb

    @property
    def mem_used_pct(self):
        # type: () -> float
        if self.mem_total_kb == 0:
            return 0.0
        return round(self.mem_used_kb / self.mem_total_kb * 100, 2)

    @property
    def swap_used_kb(self):
        # type: () -> int
        return self.swap_total_kb - self.swap_free_kb

    def to_dict(self):
        # type: () -> Dict[str, Any]
        return {
            "mem_total_kb": self.mem_total_kb,
            "mem_free_kb": self.mem_free_kb,
            "mem_available_kb": self.mem_available_kb,
            "buffers_kb": self.buffers_kb,
            "cached_kb": self.cached_kb,
            "swap_total_kb": self.swap_total_kb,
            "swap_free_kb": self.swap_free_kb,
            "timestamp": self.timestamp,
            "mem_used_kb": self.mem_used_kb,
            "mem_used_pct": self.mem_used_pct,
            "swap_used_kb": self.swap_used_kb,
        }


class IoSnapshot(object):
    """Aggregated I/O counters from ``/proc/diskstats``.

    Only *whole-disk* devices are aggregated (we skip partitions by
    checking whether the device name ends with a digit — which captures
    ``sda``, ``vda``, ``nvme0n1`` while skipping ``sda1``).  For NVMe
    devices, partition entries like ``nvme0n1p1`` are also filtered out.
    """

    __slots__ = (
        "reads_completed",
        "reads_merged",
        "sectors_read",
        "ms_reading",
        "writes_completed",
        "writes_merged",
        "sectors_written",
        "ms_writing",
        "ios_in_progress",
        "ms_doing_io",
        "weighted_ms_doing_io",
        "timestamp",
    )

    def __init__(
        self,
        reads_completed,  # type: int
        reads_merged,  # type: int
        sectors_read,  # type: int
        ms_reading,  # type: int
        writes_completed,  # type: int
        writes_merged,  # type: int
        sectors_written,  # type: int
        ms_writing,  # type: int
        ios_in_progress,  # type: int
        ms_doing_io,  # type: int
        weighted_ms_doing_io,  # type: int
        timestamp,  # type: float
    ):
        self.reads_completed = reads_completed
        self.reads_merged = reads_merged
        self.sectors_read = sectors_read
        self.ms_reading = ms_reading
        self.writes_completed = writes_completed
        self.writes_merged = writes_merged
        self.sectors_written = sectors_written
        self.ms_writing = ms_writing
        self.ios_in_progress = ios_in_progress
        self.ms_doing_io = ms_doing_io
        self.weighted_ms_doing_io = weighted_ms_doing_io
        self.timestamp = timestamp

    def to_dict(self):
        # type: () -> Dict[str, Any]
        return {
            "reads_completed": self.reads_completed,
            "reads_merged": self.reads_merged,
            "sectors_read": self.sectors_read,
            "ms_reading": self.ms_reading,
            "writes_completed": self.writes_completed,
            "writes_merged": self.writes_merged,
            "sectors_written": self.sectors_written,
            "ms_writing": self.ms_writing,
            "ios_in_progress": self.ios_in_progress,
            "ms_doing_io": self.ms_doing_io,
            "weighted_ms_doing_io": self.weighted_ms_doing_io,
            "timestamp": self.timestamp,
        }


class HostMetricsSnapshot(object):
    """A single point-in-time snapshot of host resource usage."""

    __slots__ = ("label", "cpu", "memory", "io")

    def __init__(
        self,
        label,  # type: str
        cpu=None,  # type: Optional[CpuSnapshot]
        memory=None,  # type: Optional[MemorySnapshot]
        io=None,  # type: Optional[IoSnapshot]
    ):
        self.label = label
        self.cpu = cpu
        self.memory = memory
        self.io = io


class HostConnection(object):
    """Parameters needed to reach a target host for remote command execution.

    The *reach_command* is a list of strings forming the command prefix
    that, when a remote command string is appended, produces a complete
    local command line.  Examples::

        # Plain SSH
        HostConnection("node-1", ["ssh", "ubuntu@10.0.0.1"])

        # Juju
        HostConnection("keystone/0", ["juju", "ssh", "keystone/0", "--"])

        # Kubernetes
        HostConnection("api-pod", ["kubectl", "exec", "api-pod", "--", "bash", "-c"])

    Use :func:`build_ssh_reach_command` to construct the *reach_command*
    from traditional SSH parameters (host, username, port, key file).
    """

    __slots__ = ("label", "reach_command", "command_timeout")

    def __init__(
        self,
        label,  # type: str
        reach_command,  # type: List[str]
        command_timeout=40,  # type: int
    ):
        self.label = label
        self.reach_command = list(reach_command)
        self.command_timeout = command_timeout


# ---------------------------------------------------------------------------
# Metric parsing
# ---------------------------------------------------------------------------


def _parse_cpu(raw):
    # type: (str) -> Optional[CpuSnapshot]
    """Parse the ``cpu`` aggregate line from ``/proc/stat``."""
    for line in raw.splitlines():
        if line.startswith("cpu "):
            parts = line.split()
            try:
                return CpuSnapshot(
                    user=int(parts[1]),
                    nice=int(parts[2]),
                    system=int(parts[3]),
                    idle=int(parts[4]),
                    iowait=int(parts[5]) if len(parts) > 5 else 0,
                    irq=int(parts[6]) if len(parts) > 6 else 0,
                    softirq=int(parts[7]) if len(parts) > 7 else 0,
                    steal=int(parts[8]) if len(parts) > 8 else 0,
                    timestamp=time.monotonic(),
                )
            except (IndexError, ValueError) as exc:
                _logger.warning("Failed to parse /proc/stat cpu line: %s", exc)
                return None
    return None


def _parse_meminfo(raw):
    # type: (str) -> Optional[MemorySnapshot]
    """Parse ``/proc/meminfo`` output."""
    fields = {}  # type: Dict[str, int]
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            key = parts[0].rstrip(":")
            try:
                fields[key] = int(parts[1])
            except ValueError:
                continue

    try:
        return MemorySnapshot(
            mem_total_kb=fields["MemTotal"],
            mem_free_kb=fields["MemFree"],
            mem_available_kb=fields.get("MemAvailable", fields["MemFree"]),
            buffers_kb=fields.get("Buffers", 0),
            cached_kb=fields.get("Cached", 0),
            swap_total_kb=fields.get("SwapTotal", 0),
            swap_free_kb=fields.get("SwapFree", 0),
            timestamp=time.monotonic(),
        )
    except KeyError as exc:
        _logger.warning("Failed to parse /proc/meminfo - missing key: %s", exc)
        return None


def _parse_diskstats(raw):
    # type: (str) -> Optional[IoSnapshot]
    """Parse ``/proc/diskstats`` and aggregate across all whole-disk devices."""
    totals = [0] * 11
    found_any = False

    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 14:
            continue
        dev_name = parts[2]
        # Skip partitions (names ending with a digit, e.g. sda1, nvme0n1p1)
        if dev_name[-1:].isdigit() and not dev_name.startswith("nvme"):
            continue
        # For nvme devices, skip partition entries like nvme0n1p1
        if dev_name.startswith("nvme") and "p" in dev_name.split("n", 1)[-1]:
            continue

        try:
            values = [int(parts[i]) for i in range(3, 14)]
        except (IndexError, ValueError):
            continue
        for i in range(11):
            totals[i] += values[i]
        found_any = True

    if not found_any:
        return None

    return IoSnapshot(
        reads_completed=totals[0],
        reads_merged=totals[1],
        sectors_read=totals[2],
        ms_reading=totals[3],
        writes_completed=totals[4],
        writes_merged=totals[5],
        sectors_written=totals[6],
        ms_writing=totals[7],
        ios_in_progress=totals[8],
        ms_doing_io=totals[9],
        weighted_ms_doing_io=totals[10],
        timestamp=time.monotonic(),
    )


# ---------------------------------------------------------------------------
# High-level collector
# ---------------------------------------------------------------------------


def collect_snapshot(conn, label):
    # type: (HostConnection, str) -> HostMetricsSnapshot
    """Collect a single snapshot of CPU, memory and I/O metrics.

    The three ``/proc`` files are read in a single remote invocation to
    minimise round-trip overhead.
    """
    combined_cmd = "{ %s; echo '---SEPARATOR---'; %s; echo '---SEPARATOR---'; %s; }" % (
        _CMD_CPU,
        _CMD_MEMORY,
        _CMD_IO,
    )
    raw = _exec_remote(conn, combined_cmd)

    sections = raw.split("---SEPARATOR---")
    cpu_raw = sections[0] if len(sections) > 0 else ""
    mem_raw = sections[1] if len(sections) > 1 else ""
    io_raw = sections[2] if len(sections) > 2 else ""

    return HostMetricsSnapshot(
        label=label,
        cpu=_parse_cpu(cpu_raw),
        memory=_parse_meminfo(mem_raw),
        io=_parse_diskstats(io_raw),
    )


# ---------------------------------------------------------------------------
# Diffing helpers (CPU & IO are cumulative counters)
# ---------------------------------------------------------------------------


def cpu_usage_pct(before, after):
    # type: (CpuSnapshot, CpuSnapshot) -> Dict[str, float]
    """Compute CPU usage percentages between two snapshots."""
    d_total = max(after.total - before.total, 1)
    return {
        "user_pct": round((after.user - before.user) / d_total * 100, 2),
        "nice_pct": round((after.nice - before.nice) / d_total * 100, 2),
        "system_pct": round((after.system - before.system) / d_total * 100, 2),
        "idle_pct": round((after.idle - before.idle) / d_total * 100, 2),
        "iowait_pct": round((after.iowait - before.iowait) / d_total * 100, 2),
        "irq_pct": round((after.irq - before.irq) / d_total * 100, 2),
        "softirq_pct": round((after.softirq - before.softirq) / d_total * 100, 2),
        "steal_pct": round((after.steal - before.steal) / d_total * 100, 2),
        "busy_pct": round((after.busy - before.busy) / d_total * 100, 2),
    }


def io_diff(before, after):
    # type: (IoSnapshot, IoSnapshot) -> Dict[str, int]
    """Compute I/O counter deltas between two snapshots."""
    return {
        "reads_completed": after.reads_completed - before.reads_completed,
        "sectors_read": after.sectors_read - before.sectors_read,
        "ms_reading": after.ms_reading - before.ms_reading,
        "writes_completed": after.writes_completed - before.writes_completed,
        "sectors_written": after.sectors_written - before.sectors_written,
        "ms_writing": after.ms_writing - before.ms_writing,
        "ms_doing_io": after.ms_doing_io - before.ms_doing_io,
    }


def snapshot_to_dict(snap):
    # type: (HostMetricsSnapshot) -> Dict[str, Any]
    """Serialise a snapshot to a JSON-friendly dictionary."""
    result = {"label": snap.label}  # type: Dict[str, Any]
    if snap.cpu:
        result["cpu"] = snap.cpu.to_dict()
    if snap.memory:
        result["memory"] = snap.memory.to_dict()
    if snap.io:
        result["io"] = snap.io.to_dict()
    return result


def build_rally_output_charts(snapshots):
    # type: (List[HostMetricsSnapshot]) -> List[Dict[str, Any]]
    """Build Rally ``add_output`` chart data from a list of snapshots.

    This is the **single-host** variant.  For HA / multi-host scenarios
    use :func:`build_rally_output_charts_multi` instead.

    Returns a list of *complete* output dicts that can each be passed to
    ``self.add_output(complete=...)`` inside a scenario's ``run`` method.
    """
    charts = []  # type: List[Dict[str, Any]]

    # --- Memory usage chart ---
    mem_data = []  # type: List[List[Any]]
    for snap in snapshots:
        if snap.memory:
            mem_data.append([snap.label, snap.memory.mem_used_pct])
    if mem_data:
        charts.append(
            {
                "title": "Host Memory Usage (%)",
                "description": "Percentage of memory in use at each sample point",
                "chart_plugin": "StackedArea",
                "data": [
                    ["Memory Used %", [[i, v[1]] for i, v in enumerate(mem_data)]],
                ],
                "label": "Memory %",
                "axis_label": "Sample",
            }
        )

    # --- CPU usage (requires at least two snapshots to diff) ---
    cpu_series_data = []  # type: List[List[Any]]
    for i in range(1, len(snapshots)):
        before_cpu = snapshots[i - 1].cpu
        after_cpu = snapshots[i].cpu
        if before_cpu and after_cpu:
            usage = cpu_usage_pct(before_cpu, after_cpu)
            cpu_series_data.append([snapshots[i].label, usage["busy_pct"]])
    if cpu_series_data:
        charts.append(
            {
                "title": "Host CPU Busy (%)",
                "description": "CPU busy percentage between consecutive sample points",
                "chart_plugin": "StackedArea",
                "data": [
                    ["CPU Busy %", [[i, v[1]] for i, v in enumerate(cpu_series_data)]],
                ],
                "label": "CPU %",
                "axis_label": "Sample",
            }
        )

    # --- I/O (requires at least two snapshots to diff) ---
    io_read_data = []  # type: List[List[Any]]
    io_write_data = []  # type: List[List[Any]]
    for i in range(1, len(snapshots)):
        before_io = snapshots[i - 1].io
        after_io = snapshots[i].io
        if before_io and after_io:
            delta = io_diff(before_io, after_io)
            io_read_data.append([snapshots[i].label, delta["sectors_read"]])
            io_write_data.append([snapshots[i].label, delta["sectors_written"]])
    if io_read_data or io_write_data:
        series = []  # type: List[List[Any]]
        if io_read_data:
            series.append(
                ["Sectors Read", [[i, v[1]] for i, v in enumerate(io_read_data)]]
            )
        if io_write_data:
            series.append(
                ["Sectors Written", [[i, v[1]] for i, v in enumerate(io_write_data)]]
            )
        charts.append(
            {
                "title": "Host Disk I/O (sectors)",
                "description": "Sectors read/written between consecutive sample points",
                "chart_plugin": "StackedArea",
                "data": series,
                "label": "Sectors",
                "axis_label": "Sample",
            }
        )

    # --- Detailed table with raw numbers ---
    table_data = []  # type: List[List[Any]]
    for snap in snapshots:
        d = snapshot_to_dict(snap)
        mem_used = d.get("memory", {}).get("mem_used_pct", "N/A")
        mem_total = d.get("memory", {}).get("mem_total_kb", "N/A")
        ios_in_progress = d.get("io", {}).get("ios_in_progress", "N/A")
        table_data.append(
            [
                snap.label,
                str(mem_used),
                str(mem_total),
                str(ios_in_progress),
            ]
        )
    if table_data:
        charts.append(
            {
                "title": "Host Metrics Snapshots",
                "description": "Raw metrics captured at each sample point",
                "chart_plugin": "Table",
                "data": {
                    "cols": [
                        "Sample",
                        "Memory Used %",
                        "Memory Total (kB)",
                        "IOs In Progress",
                    ],
                    "rows": table_data,
                },
            }
        )

    return charts


# ---------------------------------------------------------------------------
# Multi-host (HA) chart builder
# ---------------------------------------------------------------------------

# The four canonical sample-point labels emitted by the scenario plugin.
_SAMPLE_LABELS = ("baseline", "mid_pre_trigger", "post_trigger", "final")


def build_rally_output_charts_multi(host_snapshots):
    # type: (Dict[str, List[HostMetricsSnapshot]]) -> List[Dict[str, Any]]
    """Build Rally ``add_output`` chart data for **multiple hosts**.

    *host_snapshots* is a mapping of ``host_label -> [snap0, snap1, ...]``
    where each list contains the four chronological snapshots collected by
    the scenario plugin (baseline, mid_pre_trigger, post_trigger, final).

    Every chart contains one series **per host** so their resource usage
    can be compared side-by-side in the Rally HTML report.

    Returns a list of *complete* output dicts suitable for
    ``self.add_output(complete=...)``.
    """
    charts = []  # type: List[Dict[str, Any]]
    host_labels = sorted(host_snapshots.keys())

    # ---- Memory usage — one series per host --------------------------------
    mem_series = []  # type: List[List[Any]]
    for hlabel in host_labels:
        points = []  # type: List[List[Any]]
        for idx, snap in enumerate(host_snapshots[hlabel]):
            if snap.memory:
                points.append([idx, snap.memory.mem_used_pct])
        if points:
            mem_series.append(["%s Memory Used %%" % hlabel, points])
    if mem_series:
        charts.append(
            {
                "title": "Host Memory Usage (%) — All Hosts",
                "description": (
                    "Percentage of memory in use at each sample point, "
                    "one series per host"
                ),
                "chart_plugin": "Lines",
                "data": mem_series,
                "label": "Memory %",
                "axis_label": "Sample",
            }
        )

    # ---- CPU busy % — one series per host ----------------------------------
    cpu_series = []  # type: List[List[Any]]
    for hlabel in host_labels:
        snaps = host_snapshots[hlabel]
        points = []  # type: List[List[Any]]
        for idx in range(1, len(snaps)):
            b_cpu = snaps[idx - 1].cpu
            a_cpu = snaps[idx].cpu
            if b_cpu and a_cpu:
                usage = cpu_usage_pct(b_cpu, a_cpu)
                points.append([idx, usage["busy_pct"]])
        if points:
            cpu_series.append(["%s CPU Busy %%" % hlabel, points])
    if cpu_series:
        charts.append(
            {
                "title": "Host CPU Busy (%) — All Hosts",
                "description": (
                    "CPU busy percentage between consecutive sample points, "
                    "one series per host"
                ),
                "chart_plugin": "Lines",
                "data": cpu_series,
                "label": "CPU %",
                "axis_label": "Sample",
            }
        )

    # ---- Disk I/O sectors read — one series per host -----------------------
    io_read_series = []  # type: List[List[Any]]
    io_write_series = []  # type: List[List[Any]]
    for hlabel in host_labels:
        snaps = host_snapshots[hlabel]
        rd_points = []  # type: List[List[Any]]
        wr_points = []  # type: List[List[Any]]
        for idx in range(1, len(snaps)):
            b_io = snaps[idx - 1].io
            a_io = snaps[idx].io
            if b_io and a_io:
                delta = io_diff(b_io, a_io)
                rd_points.append([idx, delta["sectors_read"]])
                wr_points.append([idx, delta["sectors_written"]])
        if rd_points:
            io_read_series.append(["%s Sectors Read" % hlabel, rd_points])
        if wr_points:
            io_write_series.append(["%s Sectors Written" % hlabel, wr_points])
    combined_io = io_read_series + io_write_series
    if combined_io:
        charts.append(
            {
                "title": "Host Disk I/O (sectors) — All Hosts",
                "description": (
                    "Sectors read/written between consecutive sample points, "
                    "one series per host"
                ),
                "chart_plugin": "Lines",
                "data": combined_io,
                "label": "Sectors",
                "axis_label": "Sample",
            }
        )

    # ---- Raw snapshot table — one row per (host, sample) -------------------
    table_rows = []  # type: List[List[str]]
    for hlabel in host_labels:
        for snap in host_snapshots[hlabel]:
            d = snapshot_to_dict(snap)
            mem = d.get("memory", {})
            io_data = d.get("io", {})
            table_rows.append(
                [
                    hlabel,
                    snap.label,
                    str(mem.get("mem_used_pct", "N/A")),
                    str(mem.get("mem_total_kb", "N/A")),
                    str(io_data.get("reads_completed", "N/A")),
                    str(io_data.get("writes_completed", "N/A")),
                    str(io_data.get("ios_in_progress", "N/A")),
                ]
            )
    if table_rows:
        charts.append(
            {
                "title": "Host Metrics Snapshots — All Hosts",
                "description": "Raw metrics captured at each sample point per host",
                "chart_plugin": "Table",
                "data": {
                    "cols": [
                        "Host",
                        "Sample",
                        "Memory Used %",
                        "Memory Total (kB)",
                        "Disk Reads",
                        "Disk Writes",
                        "IOs In Progress",
                    ],
                    "rows": table_rows,
                },
            }
        )

    return charts