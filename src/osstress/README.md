# OsStress – Rally Stress-Test Plugins

A set of [Rally](https://docs.openstack.org/rally/latest/) plugins that
extend standard Rally-OpenStack scenarios.

## Plugins

### `OsStress.split_run`

Wraps any available Rally scenario, runs half the iterations, fires a
trigger command on one or more hosts, runs the remaining iterations, then
executes an optional cleanup command to restore the original state.  Each
half delegates to a real Rally runner instance (serial, constant, RPS, …)
so you get the runner's full feature set (concurrency, RPS throttling,
timeouts) for free.

Host metrics (CPU, memory, I/O) are collected from every target in a
background thread at a configurable interval via `/proc/stat`,
`/proc/meminfo` and `/proc/diskstats`, so snapshots reflect system state
under load rather than at idle phase boundaries.
CPU and I/O deltas are computed between consecutive snapshots.

### `OsStress.find_limits`

Wraps any available Rally scenario and runs it with progressively
increasing iteration counts.  Each step delegates to a real Rally runner
instance (serial, constant, RPS, …) so you get the runner's full feature
set (concurrency, RPS throttling, timeouts) at every load level.  After
each step the results are checked against configurable SLA thresholds
(average duration, max duration per iteration, failure rate).  The first
step that violates a threshold is recorded as the service limit.

Performance data at each load level is exported as Rally output charts
(duration vs load, failure rate vs load) alongside a summary table.

## Reaching hosts

Every target host is contacted through a **reach command** — a shell
command prefix that, when a remote command string is appended, produces a
complete local command line.  For example:

| Transport  | `reach_command` value                                    |
| ---------- | -------------------------------------------------------- |
| Plain SSH  | `"ssh -o StrictHostKeyChecking=no ubuntu@10.0.0.1"`      |
| Juju       | `"juju ssh keystone/0 --"`                               |
| Kubernetes | `["kubectl", "exec", "api-pod", "--", "bash", "-c"]`     |

There are two ways to specify how to reach a host:

1. **`reach_command`** (string or list) — provide the exact command
   prefix.  This is the most flexible option and works with any
   transport.

2. **`host`** (string) + optional SSH parameters (`username`, `port`,
   `key_file`, `connect_timeout`) — a convenience shorthand that
   automatically builds an SSH reach command.

## Usage

```shell
rally --plugin-paths src/osstress task start scenarios/keystone/stress.json
```

## Package layout

```
osstress/
├── __init__.py
├── common.py           # shared helpers (scenario resolution, run loop)
├── metrics.py          # host metrics collection and chart building
├── README.md
└── plugins/
    ├── __init__.py
    ├── split_run.py     # OsStress.split_run
    └── find_limits.py   # OsStress.find_limits
```

## Task format – `OsStress.split_run`

### Single-host mode — with `reach_command`

```json
{
    "OsStress.split_run": [{
        "args": {
            "scenario_name": "Authenticate.keystone",
            "reach_command": "juju ssh keystone/0 --",
            "trigger_command": "sudo systemctl stop keystone",
            "cleanup_command": "sudo systemctl start keystone",
            "runner": { "type": "constant", "times": 20, "concurrency": 4 },
            "command_timeout": 60
        },
        "runner": { "type": "constant", "times": 1, "concurrency": 1 },
        "context": { "users": { "tenants": 1, "users_per_tenant": 1 } }
    }]
}
```

### Single-host mode — with SSH shorthand

```json
{
    "OsStress.split_run": [{
        "args": {
            "scenario_name": "Authenticate.keystone",
            "host": "10.0.0.42",
            "username": "ubuntu",
            "key_file": "/home/rally/.ssh/id_rsa",
            "trigger_command": "sudo systemctl stop keystone",
            "cleanup_command": "sudo systemctl start keystone",
            "runner": { "type": "serial", "times": 20 }
        },
        "runner": { "type": "constant", "times": 1, "concurrency": 1 },
        "context": { "users": { "tenants": 1, "users_per_tenant": 1 } }
    }]
}
```

### Multi-host (HA) mode

```json
{
    "OsStress.split_run": [{
        "args": {
            "scenario_name": "Authenticate.keystone",
            "trigger_command": "sudo systemctl stop keystone",
            "cleanup_command": "sudo systemctl start keystone",
            "hosts": [
                {
                    "reach_command": "juju ssh keystone/0 --",
                    "label": "keystone-0"
                },
                {
                    "reach_command": "juju ssh keystone/1 --",
                    "label": "keystone-1",
                    "trigger_command": "sudo systemctl stop apache2"
                },
                {
                    "host": "10.0.0.99",
                    "label": "haproxy",
                    "username": "ubuntu",
                    "trigger_command": "",
                    "cleanup_command": ""
                }
            ],
            "runner": { "type": "constant", "times": 20, "concurrency": 4 },
            "command_timeout": 60
        },
        "runner": { "type": "constant", "times": 1, "concurrency": 1 },
        "context": { "users": { "tenants": 1, "users_per_tenant": 1 } }
    }]
}
```

## Task format – `OsStress.find_limits`

```json
{
    "OsStress.find_limits": [{
        "args": {
            "scenario_name": "Authenticate.keystone",
            "min_times": 1,
            "max_times": 50,
            "step": 5,
            "sleep": 2.0,
            "sla": {
                "failure_rate": { "max": 0 },
                "max_avg_duration": 1.0,
                "max_seconds_per_iteration": 2.0
            },
            "runner": {
                "type": "constant",
                "concurrency": 4
            },
            "scenario_args": {}
        },
        "runner": { "type": "constant", "times": 1, "concurrency": 1 },
        "context": {
            "users": { "tenants": 3, "users_per_tenant": 50 }
        }
    }]
}
```

> **Note:** Both `OsStress.split_run` and `OsStress.find_limits` have
> two `"runner"` blocks.  The **outer** one (sibling of `"args"`) is the
> standard Rally runner that executes the OsStress scenario itself —
> typically once.  The **inner** one (inside `"args"`) controls how the
> wrapped scenario is executed.  For `find_limits` the plugin overrides
> `"times"` per step, so only specify non-`times` fields like
> `"concurrency"` or `"rps"`.  For `split_run` the `"times"` field in
> the inner runner controls the **total** iteration count (split in half).

## Arguments – `OsStress.split_run`

| Argument            | Type               | Req.    | Default                          | Notes                                              |
| ------------------- | ------------------ | ------- | -------------------------------- | -------------------------------------------------- |
| `scenario_name`     | `str`              | **yes** | —                                | e.g. `"Authenticate.keystone"`                     |
| `trigger_command`   | `str`              | **yes** | —                                | Default trigger; per-host entries may override.     |
| `reach_command`     | `str \| list[str]` | —       | `null`                           | Single-host mode. Command prefix to reach the host. Mutually exclusive with `host` and `hosts`. |
| `host`              | `str`              | —       | `null`                           | Single-host SSH mode. Mutually exclusive with `reach_command` and `hosts`. |
| `hosts`             | `list[dict]`       | —       | `null`                           | Multi-host mode. Each entry has `reach_command` or `host`. Mutually exclusive with `host` and `reach_command`. |
| `scenario_args`     | `dict`             | —       | `{}`                             | Passed to the inner scenario's `run()`.            |
| `runner`            | `dict`             | —       | `{"type":"serial", "times": 10}` | Runner config — same shape as Rally's native `runner` block. `times` = total iterations (split in half). |
| `snapshot_interval` | `float`            | —       | `5.0`                            | Seconds between background host-metrics snapshots. A background thread collects CPU, memory and I/O from every target host at this interval for the entire test duration. |
| `username`          | `str`              | —       | `"ubuntu"`                       | Default SSH user (only used with `host`).          |
| `port`              | `int`              | —       | `22`                             | Default SSH port (only used with `host`).          |
| `key_file`          | `str`              | —       | `null`                           | Default SSH key (only used with `host`).           |
| `connect_timeout`   | `int`              | —       | `10`                             | SSH connection timeout in seconds (only used with `host`). |
| `command_timeout`   | `int`              | —       | `40`                             | Remote command timeout in seconds.                 |
| `trigger_wait`      | `float`            | —       | `0.0`                            | Sleep after trigger before second half.            |
| `cleanup_command`   | `str`              | —       | `""`                             | Default cleanup command. Per-host entries may override. Empty = skip. |
| `cleanup_wait`      | `float`            | —       | `0.0`                            | Sleep after cleanup before the test ends. Background metrics continue during this period. |

## Arguments – `OsStress.find_limits`

| Argument          | Type   | Req.    | Default            | Notes                                                    |
| ----------------- | ------ | ------- | ------------------ | -------------------------------------------------------- |
| `scenario_name`   | `str`  | **yes** | —                  | e.g. `"Authenticate.keystone"`                           |
| `sla`             | `dict` | —       | `{}`               | SLA criteria dict — same format as Rally's native `sla` block (see below). |
| `runner`          | `dict` | —       | `{"type":"serial"}`| Runner config for each step — same shape as Rally's native `runner` block. `times` is overridden per step. |
| `scenario_args`   | `dict` | —       | `{}`               | Passed to the inner scenario's `run()`.                  |
| `min_times`       | `int`  | —       | `1`                | Iterations at the first step.                            |
| `max_times`       | `int`  | —       | `100`              | Max iterations per step.                                 |
| `step`            | `int`  | —       | `1`                | Increment per step.                                      |
| `sleep`           | `float`| —       | `1.0`              | Seconds to pause between steps.                          |

### Supported `sla` criteria

The `sla` dict uses the **same keys and format** as Rally's native
top-level `"sla"` block.  Supported criteria:

| Key                          | Value format      | Description                                          |
| ---------------------------- | ----------------- | ---------------------------------------------------- |
| `failure_rate`               | `{"max": <0-100>}`| Max failure **percentage** (0 = no failures allowed). |
| `max_seconds_per_iteration`  | `<float>`         | Max single-iteration duration in seconds.            |
| `max_avg_duration`           | `<float>`         | Max average duration in seconds.                     |

If `sla` is empty or omitted, the search runs through all steps up to
`max_times` without stopping early.

### Inner `runner` configuration

The `runner` dict uses the **same keys and format** as Rally's native
top-level `"runner"` block.  At each step the plugin injects
`"times": <current_times>` into a copy of this dict and instantiates
the corresponding Rally runner.  Any runner that accepts `times` works
(`serial`, `constant`, `rps`, …).

| Runner type  | Useful extra fields                | Effect                                            |
| ------------ | ---------------------------------- | ------------------------------------------------- |
| `serial`     | *(none)*                           | Iterations run one-by-one in the Rally process.   |
| `constant`   | `concurrency`, `timeout`           | Parallel iterations with a fixed thread pool.     |
| `rps`        | `rps`, `max_concurrency`, `timeout`| Fixed requests-per-second with bounded concurrency.|

If `runner` is omitted the default is `{"type": "serial"}`.  For
`OsStress.find_limits` this matches the previous behaviour.  For
`OsStress.split_run` the default also sets `"times": 10` (matching
the old `total_times` default); the total is split roughly in half
for the two execution phases.

## Report output

`rally task report --out report.html` renders all plugin output — host
metrics charts, iteration timing data, trigger/cleanup command details,
and (for `find_limits`) duration-vs-load and failure-rate-vs-load charts
alongside the discovered limit summary.