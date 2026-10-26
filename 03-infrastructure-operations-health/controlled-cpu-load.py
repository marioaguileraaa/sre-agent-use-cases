"""Manually operated, bounded CPU exercise for an explicitly approved lab host.

Never install this script as an SRE tool or invoke it from a skill/task.
It has no Azure calls, memory allocation exercise or disk workload.
"""

import argparse
import json
import math
import multiprocessing
import os
import platform
import re
import signal
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

MAX_SECONDS = 480
MAX_WORKERS = 8
MAX_DUTY_FRACTION = 0.85
MAX_HOST_CPU_PERCENT = 85.0
MAX_TARGET_CPU_PERCENT = 82.0
MAX_BASELINE_CPU_PERCENT = 20.0
CONTROL_INTERVAL_SECONDS = 1.0
TARGET_CONSECUTIVE_SAMPLES = 3


class UnreachableTargetError(ValueError):
    pass


def validate_target(approved_host, actual_host, acknowledged, workers, seconds, available_cpus):
    if not acknowledged:
        raise ValueError("Explicit --acknowledge-risk is required after the operator's target-specific approval.")
    if not approved_host or approved_host.rstrip(".").casefold() != actual_host.rstrip(".").casefold():
        raise ValueError("--approved-host must exactly match this approved guest's hostname, not an ARM alias or guessed target.")
    if type(workers) is not int or not 1 <= workers <= min(MAX_WORKERS, available_cpus):
        raise ValueError("workers must be between one and the smaller of eight or the available CPU count.")
    if type(seconds) is not int or not 1 <= seconds <= MAX_SECONDS:
        raise ValueError("duration-seconds must be between one and 480.")


def parse_cpu_stat(text):
    fields = text.splitlines()[0].split() if text else []
    if len(fields) < 9 or fields[0] != "cpu" or any(not value.isdigit() for value in fields[1:9]):
        raise ValueError("Linux aggregate /proc/stat CPU counters are unavailable or malformed.")
    values = [int(value) for value in fields[1:9]]
    return sum(values), values[3] + values[4]


def cpu_percent(previous, current):
    total, idle = current[0] - previous[0], current[1] - previous[1]
    if total <= 0 or idle < 0 or idle > total:
        raise ValueError("Linux CPU counters did not advance coherently; load is stopped.")
    return (total - idle) / total * 100.0


def available_memory_bytes(text):
    match = re.search(r"^MemAvailable:\s+([0-9]+)\s+kB\s*$", text, re.MULTILINE)
    if not match:
        raise ValueError("Linux MemAvailable is not supplied; no free-memory fallback is assumed.")
    return int(match.group(1)) * 1024


def parse_cpu_max(text):
    fields = text.split()
    if len(fields) != 2 or not fields[1].isdigit() or int(fields[1]) <= 0:
        raise ValueError("cgroup v2 cpu.max is malformed; no load starts.")
    if fields[0] == "max":
        return None
    if not fields[0].isdigit() or int(fields[0]) <= 0:
        raise ValueError("cgroup v2 CPU quota must be positive or max.")
    return int(fields[0]) / int(fields[1])


def cgroup_budget(membership, mountinfo, read_cpu_max):
    paths = [line.split("::", 1)[1] for line in membership.splitlines() if line.startswith("0::")]
    if len(paths) != 1:
        raise ValueError("Only an inspectable cgroup v2 CPU hierarchy is validated; no quota fallback is assumed.")
    group = PurePosixPath(paths[0])
    if not paths[0].startswith("/") or any(part in (".", "..") for part in paths[0].split("/")):
        raise ValueError("The process cgroup path is malformed; no load starts.")
    mounts = []
    for line in mountinfo.splitlines():
        before, separator, after = line.partition(" - ")
        filesystem = after.split()
        if separator and filesystem and filesystem[0] == "cgroup2":
            fields = before.split()
            if len(fields) < 5:
                raise ValueError("The cgroup mount identity is malformed.")
            root, mount = (re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value) for value in fields[3:5])
            if root != "/" or not mount.startswith("/") or any(part in (".", "..") for part in mount.split("/")):
                raise ValueError("The complete CPU-quota hierarchy is not visible; no namespace escape or load is attempted.")
            mounts.append(PurePosixPath(mount))
    if len(mounts) != 1:
        raise ValueError("Expected one unambiguous cgroup v2 mount; no load starts.")
    mount = mounts[0]
    current = mount / str(group).lstrip("/")
    quotas, inspected = [], []
    while current != mount:
        raw = read_cpu_max(str(current / "cpu.max"))
        quota = parse_cpu_max(raw)
        inspected.append({"cgroup": "/" + str(current.relative_to(mount)), "cpu_max": raw.strip(), "quota_cores": quota})
        if quota is not None:
            quotas.append(quota)
        current = current.parent
    return {"cgroup_version": 2, "process_cgroup": str(group), "quota_cores": min(quotas) if quotas else None,
            "inspected_hierarchy": inspected, "limits_changed": False}


def _cpu_budget(cpus):
    result = cgroup_budget(
        Path("/proc/self/cgroup").read_text(encoding="ascii"),
        Path("/proc/self/mountinfo").read_text(encoding="ascii"),
        lambda path: Path(path).read_text(encoding="ascii"),
    )
    affinity = os.sched_getaffinity(0)
    if not affinity or len(affinity) > cpus:
        raise ValueError("CPU affinity is unavailable or inconsistent with the host denominator.")
    result["affinity_cpus"] = len(affinity)
    result["quota_host_cpu_percent"] = result["quota_cores"] / cpus * 100 if result["quota_cores"] is not None else None
    return result


def validate_preflight(system, baseline, available, workers, target, cpus, budget=None):
    if system != "Linux":
        raise ValueError("This safety-controlled exercise is validated only for Linux /proc telemetry.")
    if not isinstance(target, (int, float)) or isinstance(target, bool) or not math.isfinite(target) or not 1 <= target <= MAX_TARGET_CPU_PERCENT:
        raise ValueError("target-cpu-percent must be finite and between one and 82; the sampled stop ceiling remains 85.")
    if not math.isfinite(baseline) or not 0 <= baseline <= MAX_BASELINE_CPU_PERCENT:
        raise ValueError("Baseline CPU exceeds the 20% dedicated-lab preflight limit; no load starts.")
    if available < (256 + 64 * workers) * 1024 * 1024:
        raise ValueError("Available memory is below the worker safety reserve; no load starts.")
    maximum_cores = min(workers, budget["affinity_cpus"] if budget is not None else cpus) * MAX_DUTY_FRACTION
    if budget is not None and budget["quota_cores"] is not None:
        maximum_cores = min(maximum_cores, budget["quota_cores"])
    if baseline + maximum_cores / cpus * 100 < target:
        raise UnreachableTargetError(
            "Requested host-CPU target is unreachable within the observed cgroup/affinity and bounded workers. "
            f"Maximum additional capacity is {maximum_cores / cpus * 100:.3f} host percentage points. "
            "No workers started, quotas changed or agent governance bypassed."
        )


def target_sample_matches(observed, target):
    return observed >= target - max(1.0, target * 0.05)


def adjusted_duty(duty, observed, target, cpus, workers):
    if observed > MAX_HOST_CPU_PERCENT:
        raise ValueError("Observed aggregate host CPU exceeded the sampled 85% stop ceiling.")
    change = max(-0.03, min(0.03, (target - observed) / 100.0 * cpus / workers * 0.35))
    return max(0.0, min(MAX_DUTY_FRACTION, duty + change))


def _cpu_sample():
    return parse_cpu_stat(Path("/proc/stat").read_text(encoding="ascii"))


def _memory_sample():
    return available_memory_bytes(Path("/proc/meminfo").read_text(encoding="ascii"))


def _worker(deadline, stop, duty):
    value = 0.0
    cycle_seconds = 0.1
    while time.monotonic() < deadline and not stop.is_set():
        cycle_start = time.monotonic()
        busy_end = min(deadline, cycle_start + cycle_seconds * min(MAX_DUTY_FRACTION, max(0.0, duty.value)))
        while time.monotonic() < busy_end:
            for index in range(200):
                value += math.sqrt(index + 1)
            if value > 1e12:
                value = 0.0
        stop.wait(max(0.0, min(deadline, cycle_start + cycle_seconds) - time.monotonic()))


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main():
    parser = argparse.ArgumentParser(description="Operator-only bounded CPU load on one previously approved, dedicated lab guest.")
    parser.add_argument("--approved-host", required=True, help="Exact guest hostname already approved by the user.")
    parser.add_argument("--acknowledge-risk", action="store_true", help="Confirm target-specific approval and an independent stop channel.")
    parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 1, MAX_WORKERS))
    parser.add_argument("--duration-seconds", type=int, default=360)
    parser.add_argument("--target-cpu-percent", type=float, default=82.0, help="Sampled aggregate host target, at most 82 percent; stop ceiling is 85 percent.")
    parser.add_argument("--baseline-only", action="store_true", help="Read Linux baseline/safety data and exit without creating workers.")
    args = parser.parse_args()
    actual_host = socket.gethostname()
    try:
        validate_target(args.approved_host, actual_host, args.acknowledge_risk or args.baseline_only,
                        args.workers, args.duration_seconds, os.cpu_count() or 1)
        if platform.system() != "Linux":
            raise ValueError("The bounded load controller requires actual Linux /proc counters; no load starts on this OS.")
    except ValueError as exc:
        parser.error(str(exc))
    context = multiprocessing.get_context("spawn")
    stop = context.Event()
    duty = context.Value("d", 0.0)
    deadline = None
    children = []
    stopped_by_signal = False

    def request_stop(signum, _frame):
        nonlocal stopped_by_signal
        stopped_by_signal = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    reason, error = "deadline", None
    samples, matching_run, longest_run = [], 0, 0
    try:
        first = _cpu_sample()
        if stopped_by_signal or stop.wait(3.0) or stopped_by_signal:
            reason = "operator_signal"
            print(json.dumps({"status": "cancelled", "phase": "baseline", "all_workers_stopped": True,
                              "workers_started": 0}), flush=True)
            return 0
        baseline = cpu_percent(first, _cpu_sample())
        available = _memory_sample()
        cpus = os.cpu_count() or 1
        budget = _cpu_budget(cpus)
        validate_preflight(platform.system(), baseline, available, args.workers, args.target_cpu_percent, cpus, budget)
        print(json.dumps({
            "status": "baseline", "hostname": actual_host, "observed_utc": _utc(),
            "cpu_percent": baseline, "available_memory_bytes": available,
            "available_cpus": cpus, "workers": args.workers,
            "target_cpu_percent": args.target_cpu_percent, "sampled_stop_ceiling_percent": MAX_HOST_CPU_PERCENT,
            "worker_duty_ceiling_percent": MAX_DUTY_FRACTION * 100,
            "maximum_load_seconds": MAX_SECONDS, "baseline_only": args.baseline_only,
            "cpu_budget": budget,
        }), flush=True)
        if args.baseline_only:
            return 0
        if stopped_by_signal:
            print(json.dumps({"status": "cancelled", "phase": "preflight", "all_workers_stopped": True,
                              "workers_started": 0}), flush=True)
            return 0
        duty.value = min(MAX_DUTY_FRACTION, max(0.0, (args.target_cpu_percent - baseline) / 100.0 * cpus / args.workers))
        deadline = time.monotonic() + args.duration_seconds
        for _ in range(args.workers):
            if stopped_by_signal:
                break
            child = context.Process(target=_worker, args=(deadline, stop, duty), daemon=True)
            child.start()
            children.append(child)
        print(json.dumps({
            "status": "started", "hostname": actual_host, "started_utc": _utc(),
            "parent_pid": os.getpid(), "worker_pids": [child.pid for child in children],
            "duration_seconds": args.duration_seconds, "workers": args.workers,
            "target_cpu_percent": args.target_cpu_percent,
            "sampled_stop_ceiling_percent": MAX_HOST_CPU_PERCENT, "duty_fraction": duty.value,
            "memory_exercise": False, "disk_exercise": False, "cloud_writes": False,
        }), flush=True)
        previous = _cpu_sample()
        while time.monotonic() < deadline and not stopped_by_signal and not stop.is_set():
            if any(not child.is_alive() for child in children):
                if time.monotonic() >= deadline:
                    break
                raise RuntimeError("A CPU worker exited unexpectedly; stopping the complete exercise.")
            if stop.wait(min(CONTROL_INTERVAL_SECONDS, max(0.0, deadline - time.monotonic()))) or stopped_by_signal:
                break
            if time.monotonic() >= deadline:
                break
            current = _cpu_sample()
            observed = cpu_percent(previous, current)
            previous = current
            samples.append(observed)
            matching_run = matching_run + 1 if target_sample_matches(observed, args.target_cpu_percent) else 0
            longest_run = max(longest_run, matching_run)
            duty.value = adjusted_duty(duty.value, observed, args.target_cpu_percent, cpus, args.workers)
            validate_preflight(platform.system(), 0.0, _memory_sample(), args.workers, args.target_cpu_percent, cpus)
            print(json.dumps({"status": "sample", "observed_utc": _utc(), "host_cpu_percent": observed,
                              "duty_fraction": duty.value}), flush=True)
        if not stopped_by_signal and longest_run < TARGET_CONSECUTIVE_SAMPLES:
            raise UnreachableTargetError(
                "The bounded run ended without three consecutive samples reaching the target tolerance. "
                "CPU quota, contention or lifecycle may constrain demand; no alert or successful saturation is claimed."
            )
    except (OSError, RuntimeError, ValueError) as exc:
        error = str(exc)
        reason = "safety_abort"
        print(json.dumps({"status": "error", "code": "unreachable_target" if isinstance(exc, UnreachableTargetError) else "load_safety_abort",
                          "message": error}), file=sys.stderr, flush=True)
    finally:
        stop.set()
        for child in children:
            child.join(timeout=2)
            if child.is_alive():
                child.terminate()
                child.join(timeout=2)
            if child.is_alive():
                child.kill()
                child.join(timeout=2)
        survivors = [child.pid for child in children if child.is_alive()]
        if survivors:
            print(json.dumps({"status": "cleanup_error", "surviving_worker_pids": survivors,
                              "hard_deadline_seconds": args.duration_seconds}), file=sys.stderr, flush=True)
    if survivors:
        return 1
    print(json.dumps({
        "status": "stopped", "hostname": actual_host, "stopped_utc": _utc(),
        "parent_pid": os.getpid(), "worker_pids": [child.pid for child in children],
        "reason": "operator_signal" if stopped_by_signal else reason,
        "all_workers_stopped": True,
        "target_achieved": longest_run >= TARGET_CONSECUTIVE_SAMPLES,
        "criterion": {"consecutive_samples": TARGET_CONSECUTIVE_SAMPLES,
                      "minimum_cpu_percent": args.target_cpu_percent - max(1.0, args.target_cpu_percent * 0.05)},
        "observed_samples": len(samples), "observed_cpu_mean_percent": sum(samples) / len(samples) if samples else None,
        "observed_cpu_max_percent": max(samples) if samples else None,
    }), flush=True)
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(main())
