"""Persistent remote shell for multiplexing commands over one connection."""

import logging
import queue
import shlex
import subprocess
import threading
import time
from typing import Self

_logger = logging.getLogger(__name__)


class PersistentShell:
    """A persistent remote shell that multiplexes commands over one connection.

    Instead of spawning a new subprocess (and establishing a new SSH /
    ``juju ssh`` / ``kubectl exec`` session) for every command, this
    class keeps a single ``bash`` process running on the remote host and
    sends commands through its stdin.  Output is delimited by unique
    sentinel strings so that each :meth:`exec_command` call can
    reliably extract only its own output from the shared stdout stream.

    This is **transport-agnostic** — it works with any *reach_command*
    prefix that ultimately yields an interactive shell::

        shell = PersistentShell(["ssh", "ubuntu@10.0.0.1"])
        shell.open()
        print(shell.exec_command("hostname"))
        shell.close()

    Or as a context manager::

        with PersistentShell(["juju", "ssh", "keystone/0", "--"]) as sh:
            print(sh.exec_command("cat /proc/stat"))

    The shell is thread-safe — multiple threads may call
    :meth:`exec_command` concurrently (they are serialised internally).
    """

    def __init__(self, reach_command: list[str], command_timeout: int = 40) -> None:
        self._reach_command = list(reach_command)
        self._command_timeout = command_timeout
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._stdout_q: queue.Queue[str | None] = queue.Queue()
        self._counter = 0

    def open(self) -> None:
        """Start the persistent remote shell.

        Launches ``bash`` through the *reach_command* prefix and starts
        a background reader thread that feeds stdout lines into an
        internal queue.
        """
        if self._proc is not None:
            return
        self._proc = subprocess.Popen(
            self._reach_command + ["bash"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,  # line-buffered
        )
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            daemon=True,
            name="persistent-shell-reader",
        )
        self._reader_thread.start()
        _logger.debug(
            "Persistent shell opened: %s",
            " ".join(shlex.quote(c) for c in self._reach_command),
        )

    def close(self) -> None:
        """Shut down the persistent remote shell."""
        if self._proc is None:
            return
        try:
            self._proc.stdin.close()  # type: ignore[union-attr]
        except OSError:
            pass
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        self._proc = None
        _logger.debug("Persistent shell closed")

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.close()

    # -- properties ---------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        """``True`` if the underlying process is still running."""
        return self._proc is not None and self._proc.poll() is None

    # -- command execution --------------------------------------------------

    def exec_command(self, cmd: str, timeout: int | None = None) -> str:
        """Execute *cmd* in the remote shell and return its stdout.

        Commands are serialised internally so this method is safe to
        call from multiple threads.

        Raises :class:`RuntimeError` if the shell has died and
        :class:`TimeoutError` if *timeout* (or the default
        ``command_timeout``) is exceeded.
        """
        timeout = timeout or self._command_timeout

        with self._lock:
            if not self.is_alive:
                raise RuntimeError("Persistent shell is not running")

            self._counter += 1
            sentinel = "---OSSTRESS-SHELL-END-%d---" % self._counter

            wrapped = "%s\necho '%s'\n" % (cmd, sentinel)
            self._proc.stdin.write(wrapped)  # type: ignore[union-attr]
            self._proc.stdin.flush()  # type: ignore[union-attr]

            output_lines: list[str] = []
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        "Persistent shell command timed out after %ds" % timeout
                    )
                try:
                    line = self._stdout_q.get(timeout=remaining)
                except queue.Empty:
                    raise TimeoutError(
                        "Persistent shell command timed out after %ds" % timeout
                    )
                if line is None:
                    raise RuntimeError("Persistent shell process exited unexpectedly")
                if sentinel in line:
                    break
                output_lines.append(line)
            return "".join(output_lines)

    # -- internal -----------------------------------------------------------

    def _reader_loop(self) -> None:
        """Background thread: read stdout lines into the queue."""
        try:
            while True:
                line = self._proc.stdout.readline()  # type: ignore[union-attr]
                if not line:  # EOF
                    break
                self._stdout_q.put(line)
        except (ValueError, OSError):
            pass
        # Signal EOF so any blocked exec_command wakes up.
        self._stdout_q.put(None)
