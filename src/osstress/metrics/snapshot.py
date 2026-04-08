"""Metric snapshot dataclasses with parsing and diffing capabilities."""

import dataclasses
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Self

_logger = logging.getLogger(__name__)


class Snapshot(ABC):
    """Abstract base for a single-file ``/proc`` metric snapshot."""

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Serialise the snapshot to a JSON-friendly dictionary."""

    @classmethod
    @abstractmethod
    def parse(cls, raw: str) -> "Self | None":
        """Parse raw text from :meth:`proc_file` into a snapshot instance."""

    @staticmethod
    @abstractmethod
    def proc_file() -> str:
        """Return the absolute path of the ``/proc`` file to read."""


@dataclasses.dataclass(frozen=True, slots=True)
class CpuSnapshot(Snapshot):
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

    total: int = dataclasses.field(init=False)
    busy: int = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        total = (
            self.user
            + self.nice
            + self.system
            + self.idle
            + self.iowait
            + self.irq
            + self.softirq
            + self.steal
        )
        object.__setattr__(self, "total", total)
        object.__setattr__(self, "busy", total - self.idle - self.iowait)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @staticmethod
    def proc_file() -> str:
        """Return the path to ``/proc/stat``."""
        return "/proc/stat"

    @classmethod
    def parse(cls, raw: str) -> Self | None:
        """Parse the ``cpu`` aggregate line from the full ``/proc/stat`` output."""
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


@dataclasses.dataclass(frozen=True, slots=True)
class MemorySnapshot(Snapshot):
    """Parsed subset of ``/proc/meminfo`` (values in kB)."""

    mem_total_kb: int
    mem_free_kb: int
    mem_available_kb: int
    buffers_kb: int
    cached_kb: int
    swap_total_kb: int
    swap_free_kb: int
    timestamp: float

    mem_used_kb: int = dataclasses.field(init=False)
    swap_used_kb: int = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "mem_used_kb", self.mem_total_kb - self.mem_available_kb
        )
        object.__setattr__(self, "swap_used_kb", self.swap_total_kb - self.swap_free_kb)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @staticmethod
    def proc_file() -> str:
        """Return the path to ``/proc/meminfo``."""
        return "/proc/meminfo"

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


@dataclasses.dataclass(frozen=True, slots=True)
class IoSnapshot(Snapshot):
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

    @staticmethod
    def proc_file() -> str:
        """Return the path to ``/proc/diskstats``."""
        return "/proc/diskstats"

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


@dataclasses.dataclass(frozen=True, slots=True)
class NetSnapshot(Snapshot):
    """Aggregated network counters from ``/proc/net/dev``.

    Counters are summed across all non-loopback interfaces.
    """

    rx_bytes: int
    rx_packets: int
    rx_errors: int
    rx_drops: int
    tx_bytes: int
    tx_packets: int
    tx_errors: int
    tx_drops: int
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @staticmethod
    def proc_file() -> str:
        """Return the path to ``/proc/net/dev``."""
        return "/proc/net/dev"

    @classmethod
    def parse(cls, raw: str) -> Self | None:
        """Parse ``/proc/net/dev`` and aggregate across non-loopback interfaces."""
        totals = [0] * 8
        found_any = False

        for line in raw.splitlines():
            line = line.strip()
            if ":" not in line:
                continue
            iface, _, rest = line.partition(":")
            iface = iface.strip()
            # Skip loopback
            if iface == "lo":
                continue
            parts = rest.split()
            if len(parts) < 16:
                continue
            try:
                # Receive:  bytes packets errs drop fifo frame compressed multicast
                # Transmit: bytes packets errs drop fifo colls carrier compressed
                totals[0] += int(parts[0])  # rx_bytes
                totals[1] += int(parts[1])  # rx_packets
                totals[2] += int(parts[2])  # rx_errors
                totals[3] += int(parts[3])  # rx_drops
                totals[4] += int(parts[8])  # tx_bytes
                totals[5] += int(parts[9])  # tx_packets
                totals[6] += int(parts[10])  # tx_errors
                totals[7] += int(parts[11])  # tx_drops
            except (IndexError, ValueError):
                continue
            found_any = True

        if not found_any:
            return None

        return cls(
            rx_bytes=totals[0],
            rx_packets=totals[1],
            rx_errors=totals[2],
            rx_drops=totals[3],
            tx_bytes=totals[4],
            tx_packets=totals[5],
            tx_errors=totals[6],
            tx_drops=totals[7],
            timestamp=time.monotonic(),
        )

    def diff(self, after: Self) -> dict[str, int]:
        """Compute network counter deltas between *self* and *after*."""
        return {
            "rx_bytes": after.rx_bytes - self.rx_bytes,
            "rx_packets": after.rx_packets - self.rx_packets,
            "rx_errors": after.rx_errors - self.rx_errors,
            "rx_drops": after.rx_drops - self.rx_drops,
            "tx_bytes": after.tx_bytes - self.tx_bytes,
            "tx_packets": after.tx_packets - self.tx_packets,
            "tx_errors": after.tx_errors - self.tx_errors,
            "tx_drops": after.tx_drops - self.tx_drops,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class HostMetricsSnapshot:
    """A single point-in-time snapshot of host resource usage."""

    label: str
    cpu: CpuSnapshot | None = None
    memory: MemorySnapshot | None = None
    io: IoSnapshot | None = None
    net: NetSnapshot | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise the snapshot to a JSON-friendly dictionary."""
        return dataclasses.asdict(self)
