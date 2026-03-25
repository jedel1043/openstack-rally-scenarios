"""OpenStack Rally stress-test plugins.

This package provides Rally scenario plugins that extend standard
Rally-OpenStack scenarios:

* **OsStress.split_run** (``plugins/split_run``) — split-run
  execution with host-level metrics.  Run half of the planned iterations,
  fire a trigger command on one or more target hosts, then run the
  remaining iterations.  Multi-host / HA support with per-host triggers
  and parallel metrics collection.

* **OsStress.find_limits** (``plugins/find_limits``) — automated limit
  finding.  Incrementally increase the number of iterations of a wrapped
  scenario until configurable SLA thresholds (avg duration, max duration,
  failure rate) are breached.  The discovered limit and per-step
  performance data are exported to the Rally HTML report.

Transport-agnostic host access
------------------------------
Target hosts can be reached via plain SSH, ``juju ssh``, ``kubectl exec``,
or any other command that can relay a shell command to a remote machine.
Each host is described by a *reach_command* — a command prefix that, when
a remote command string is appended, produces a complete local command
line.  Traditional SSH parameters (``host``, ``username``, ``port``,
``key_file``) are still supported as a convenience shorthand.

Package layout
--------------
::

    osstress/
    ├── __init__.py      ← this file
    ├── common.py        ← shared helpers (scenario resolution, run loop)
    ├── metrics.py       ← host metrics collection and chart building
    └── plugins/
        ├── __init__.py
        ├── split_run.py    ← OsStress.split_run
        └── find_limits.py    ← OsStress.find_limits

Usage
-----
::

    rally --plugin-paths src/osstress task start scenarios/keystone/stress.json

Or set the ``RALLY_PLUGIN_PATHS`` environment variable::

    export RALLY_PLUGIN_PATHS=src/osstress
"""