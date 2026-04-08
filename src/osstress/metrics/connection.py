"""Host connection descriptor with remote command execution."""

import logging
import shlex
import subprocess

from metrics._shell import PersistentShell
from metrics.snapshot import (
    CpuSnapshot,
    HostMetricsSnapshot,
    IoSnapshot,
    MemorySnapshot,
)

_CMD_CPU = r"grep -E '^cpu ' /proc/stat"
_CMD_MEMORY = "cat /proc/meminfo"
_CMD_IO = "cat /proc/diskstats"

_logger = logging.getLogger(__name__)


class HostConnection:
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
    """

    __slots__ = ("label", "reach_command", "command_timeout", "shell")

    def __init__(
        self,
        label: str,
        reach_command: list[str],
        command_timeout: int = 40,
        shell: PersistentShell | None = None,
    ) -> None:
        self.label = label
        self.reach_command = list(reach_command)
        self.command_timeout = command_timeout
        self.shell = shell

    def exec_remote(self, remote_cmd: str) -> str:
        """Execute *remote_cmd* on this host and return stdout.

        If a live :class:`~metrics._shell.PersistentShell` is attached,
        the command is sent through the existing connection, avoiding the
        overhead of spawning a new process and establishing a new remote
        session.

        Otherwise the full command executed locally is
        ``self.reach_command + [remote_cmd]``.  This works for any
        transport — SSH, ``juju ssh``, ``kubectl exec``, etc.
        """
        shell = getattr(self, "shell", None)
        if shell is not None and shell.is_alive:
            _logger.debug(
                "Remote exec on %s (persistent): %s",
                self.label,
                remote_cmd,
            )
            try:
                return shell.exec_command(remote_cmd, timeout=self.command_timeout)
            except Exception:
                _logger.warning(
                    "Persistent shell failed on %s, falling back to subprocess",
                    self.label,
                    exc_info=True,
                )

        cmd = list(self.reach_command) + [remote_cmd]
        _logger.debug(
            "Remote exec on %s: %s",
            self.label,
            " ".join(shlex.quote(c) for c in cmd),
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.command_timeout,
        )
        if result.returncode != 0:
            _logger.warning(
                "Remote command failed on %s (rc=%d): %s\nstderr: %s",
                self.label,
                result.returncode,
                remote_cmd,
                result.stderr.strip(),
            )
        return result.stdout

    def collect_snapshot(self, label: str) -> HostMetricsSnapshot:
        """Collect a single snapshot of CPU, memory and I/O metrics.

        The three ``/proc`` files are read in a single remote invocation
        to minimise round-trip overhead.
        """

        combined_cmd = (
            "{ %s; echo '---SEPARATOR---'; %s; echo '---SEPARATOR---'; %s; }"
            % (_CMD_CPU, _CMD_MEMORY, _CMD_IO)
        )
        raw = self.exec_remote(combined_cmd)

        sections = raw.split("---SEPARATOR---")
        cpu_raw = sections[0] if len(sections) > 0 else ""
        mem_raw = sections[1] if len(sections) > 1 else ""
        io_raw = sections[2] if len(sections) > 2 else ""

        return HostMetricsSnapshot(
            label=label,
            cpu=CpuSnapshot.parse(cpu_raw),
            memory=MemorySnapshot.parse(mem_raw),
            io=IoSnapshot.parse(io_raw),
        )
