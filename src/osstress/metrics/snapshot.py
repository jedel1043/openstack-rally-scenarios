"""Metric snapshot dataclasses with parsing and diffing capabilities."""


import dataclasses
import logging
import time
from typing import Any, Self

_logger = logging.getLogger(__name__)


@dataclasses.dataclass(slots=True)
class CpuSnapshot:
    """Raw counters from ``/proc/stat`` (first ``cpu`` line)."""

    user: int
    nice: int
    system: int
    idle: int
    iowait: int
    irq: int
    softirq: int
    steal: int
    timestamp: float

    @property
    def total(self) -> int:
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
    def busy(self) -> int:
        return self.total - self.idle - self.iowait

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def parse(cls, raw: str) -> Self | None:
        """Parse the ``cpu`` aggregate line from ``/proc/stat`` output."""
        for line in raw.splitlines():
            if line.startswith("cpu "):
                parts = line.split()
                try:
                    return cls(
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

    def usage_pct(self, after: Self) -> dict[str, float]:
        """Compute CPU usage percentages between *self* and *after*."""
        d_total = max(after.total - self.total, 1)
        return {
            "user_pct": round((after.user - self.user) / d_total * 100, 2),
            "nice_pct": round((after.nice - self.nice) / d_total * 100, 2),
            "system_pct": round((after.system - self.system) / d_total * 100, 2),
            "idle_pct": round((after.idle - self.idle) / d_total * 100, 2),
            "iowait_pct": round((after.iowait - self.iowait) / d_total * 100, 2),
            "irq_pct": round((after.irq - self.irq) / d_total * 100, 2),
            "softirq_pct": round((after.softirq - self.softirq) / d_total * 100, 2),
            "steal_pct": round((after.steal - self.steal) / d_total * 100, 2),
            "busy_pct": round((after.busy - self.busy) / d_total * 100, 2),
        }


@dataclasses.dataclass(slots=True)
class MemorySnapshot:
    """Parsed subset of ``/proc/meminfo`` (values in kB)."""

    mem_total_kb: int
    mem_free_kb: int
    mem_available_kb: int
    buffers_kb: int
    cached_kb: int
    swap_total_kb: int
    swap_free_kb: int
    timestamp: float

    @property
    def mem_used_kb(self) -> int:
        return self.mem_total_kb - self.mem_available_kb

    @property
    def mem_used_pct(self) -> float:
        if self.mem_total_kb == 0:
            return 0.0
        return round(self.mem_used_kb / self.mem_total_kb * 100, 2)

    @property
    def swap_used_kb(self) -> int:
        return self.swap_total_kb - self.swap_free_kb

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["mem_used_kb"] = self.mem_used_kb
        d["mem_used_pct"] = self.mem_used_pct
        d["swap_used_kb"] = self.swap_used_kb
        return d

    @classmethod
    def parse(cls, raw: str) -> Self | None:
        """Parse ``/proc/meminfo`` output."""
        fields: dict[str, int] = {}
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":")
                try:
                    fields[key] = int(parts[1])
                except ValueError:
                    continue

        try:
            return cls(
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


@dataclasses.dataclass(slots=True)
class IoSnapshot:
    """Aggregated I/O counters from ``/proc/diskstats``."""

    reads_completed: int
    reads_merged: int
    sectors_read: int
    ms_reading: int
    writes_completed: int
    writes_merged: int
    sectors_written: int
    ms_writing: int
    ios_in_progress: int
    ms_doing_io: int
    weighted_ms_doing_io: int
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def parse(cls, raw: str) -> Self | None:
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

        return cls(
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

    # -- diffing ------------------------------------------------------------

    def diff(self, after: Self) -> dict[str, int]:
        """Compute I/O counter deltas between *self* and *after*."""
        return {
            "reads_completed": after.reads_completed - self.reads_completed,
            "sectors_read": after.sectors_read - self.sectors_read,
            "ms_reading": after.ms_reading - self.ms_reading,
            "writes_completed": after.writes_completed - self.writes_completed,
            "sectors_written": after.sectors_written - self.sectors_written,
            "ms_writing": after.ms_writing - self.ms_writing,
            "ms_doing_io": after.ms_doing_io - self.ms_doing_io,
        }


@dataclasses.dataclass(slots=True)
class HostMetricsSnapshot:
    """A single point-in-time snapshot of host resource usage."""

    label: str
    cpu: CpuSnapshot | None = None
    memory: MemorySnapshot | None = None
    io: IoSnapshot | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise the snapshot to a JSON-friendly dictionary."""
        result: dict[str, Any] = {"label": self.label}
        if self.cpu:
            result["cpu"] = self.cpu.to_dict()
        if self.memory:
            result["memory"] = self.memory.to_dict()
        if self.io:
            result["io"] = self.io.to_dict()
        return result
