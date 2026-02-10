#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Iteratively runs a service `limits.json` task, increasing the number of concurrent
requests until Rally reports an SLA failure, or max-times is reached.
"""

import argparse
import datetime as dt
import json
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RunLimitsError(Exception):
    pass


@dataclass(frozen=True)
class RunOptions:
    min_times: int
    max_times: int | None
    step: int
    sleep: int
    rally_bin: str
    rally_opts: list[str]
    service_name: str
    task: dict[str, Any]


def get_min_times(task: dict[str, Any], scenario: str) -> int:
    try:
        for key, value in task.items():
            if not isinstance(value, list) or len(value) == 0:
                continue

            for subtask in value:
                times = subtask["runner"]["times"]
                if isinstance(times, int):
                    return times
    except KeyError:
        # Only skip KeyError. Rest of the exceptions should be propagated.
        pass

    raise RunLimitsError(
        f"could not determine minimum number of subtasks from limits.json file (key={scenario})"
    )


def update_runner_times(task: dict[str, Any], times: int):
    try:
        for key, value in task.items():
            if not isinstance(value, list) or len(value) == 0:
                continue

            for subtask in value:
                subtask["runner"]["times"] = times

    except KeyError as e:
        raise RunLimitsError(f"invalid limits.json file: {e}")


def run_iterations(
    workdir: Path,
    options: RunOptions,
):
    print(f"{options}")

    times = options.min_times
    iteration = 0
    while True:
        iteration += 1

        if options.max_times and times > options.max_times:
            print(f"Reached MAX_TIMES ({options.max_times}). Stopping.")
            return

        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        taskfile = workdir / f"rally-iter-{ts}-iter{iteration}-times{times}.json"

        update_runner_times(options.task, times)

        with taskfile.open("w", encoding="utf-8") as f:
            json.dump(options.task, f, indent=2, sort_keys=True)

        print(f"== Iteration {iteration} ({times} subtasks)")
        cmd = (
            [options.rally_bin, "task", "start", str(taskfile)]
            + options.rally_opts
            + ["--tag", options.service_name, "limits", str(times)]
        )
        print(f"Running command `{' '.join(cmd)}`\n")

        rc = subprocess.run(cmd).returncode

        if rc == 2:
            print("\nRally task failed SLA requirements. Stopping iterations.")
            print(f"Last run: runner.times={times}")
            print(f"Taskfile: {taskfile}")

        if rc != 0:
            raise RunLimitsError("Rally command exited non-zero.")

        print("\nNo SLA failure detected. Continuing...\n")

        time.sleep(options.sleep)

        times += options.step


def main() -> int:
    def pos_int(value: str) -> int:
        try:
            ivalue = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"'{value}' is not an integer") from exc
        if ivalue < 0:
            raise argparse.ArgumentTypeError(f"'{value}' must be a positive integer")
        return ivalue

    ap = argparse.ArgumentParser(
        description="Incrementally run a service's `limits.json` task until SLA failure."
    )
    ap.add_argument(
        "service_name",
        help="Service name (keystone, glance, designate, ...).",
    )
    ap.add_argument(
        "--min-times",
        type=pos_int,
        default=1,
        help="Minimum number of subtasks to run (default: 1).",
    )
    ap.add_argument(
        "--max-times",
        type=pos_int,
        help="Maximum number of subtasks to run.",
    )
    ap.add_argument(
        "--step",
        type=pos_int,
        default=1,
        help="Increment per iteration (default: 1).",
    )
    ap.add_argument(
        "--sleep",
        type=pos_int,
        default=1,
        help="Seconds to sleep between iterations (default: 1).",
    )
    ap.add_argument(
        "--rally-bin",
        default="rally",
        help="Rally CLI executable (default: rally).",
    )
    ap.add_argument(
        "--rally-opts",
        default="",
        help="Extra args passed to `rally task start`.",
    )

    args = ap.parse_args()
    service_name = args.service_name

    script_dir = Path(__file__).resolve().parent.parent
    limits_file = script_dir / service_name / "limits.json"

    if not limits_file.exists():
        raise RunLimitsError(
            f"limits file not found for service '{service_name}': {limits_file}"
        )

    rally_bin = args.rally_bin
    if shutil.which(rally_bin) is None:
        raise RunLimitsError(f"'{rally_bin}' not found in PATH")

    min_times = args.min_times
    max_times = args.max_times
    step = args.step
    sleep = args.sleep

    rally_opts = shlex.split(args.rally_opts)

    try:
        with limits_file.open("r", encoding="utf-8") as f:
            limits = json.load(f)
    except FileNotFoundError:
        raise RunLimitsError(f"limits file not found: {limits_file}")
    except json.JSONDecodeError as exc:
        raise RunLimitsError(f"failed to parse JSON from {limits_file}: {exc}")

    scenario = next(iter(limits.keys()))

    print(f"Scenario: {scenario}")
    print(f"Base file: {limits_file}")

    options = RunOptions(
        min_times=min_times or get_min_times(limits, scenario),
        max_times=max_times,
        step=step,
        sleep=sleep,
        rally_bin=rally_bin,
        rally_opts=rally_opts,
        service_name=service_name,
        task=limits,
    )

    with tempfile.TemporaryDirectory(prefix="rally-iter-") as tempdir_name:
        workdir = Path(tempdir_name)
        print(f"Workdir: {workdir}\n")
        return run_iterations(
            workdir=workdir,
            options=options,
        )


if __name__ == "__main__":
    main()
