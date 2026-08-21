#!/usr/bin/env python3
"""Exercise every K8s observability scenario and score its observable state."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = Path(__file__).with_name("k8s_scenario_cases.jsonl")
LOADER = ROOT / "k8s" / "load-scenario.sh"
PROM_URL = os.environ.get("K8S_PROMETHEUS_URL", "http://127.0.0.1:9090").rstrip("/")


def run(cmd: list[str], timeout: int = 240) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout)


def kubectl_json(*args: str) -> dict:
    result = run(["kubectl", *args], timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout)


def prometheus_query(expr: str, retries: int = 8) -> list[dict]:
    url = f"{PROM_URL}/api/v1/query?query={quote(expr, safe='')}"
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urlopen(url, timeout=8) as response:
                payload = json.load(response)
            if payload.get("status") != "success":
                raise RuntimeError(str(payload))
            return payload.get("data", {}).get("result", [])
        except (OSError, URLError, ValueError, RuntimeError) as exc:
            last_error = exc
            time.sleep(min(3, 0.75 * (attempt + 1)))
    raise RuntimeError(f"Prometheus query failed: {expr}: {last_error}")


def deployment_replicas() -> dict[str, dict[str, int]]:
    payload = kubectl_json("-n", "observability", "get", "deploy", "-o", "json")
    result: dict[str, dict[str, int]] = {}
    for item in payload.get("items", []):
        name = item["metadata"]["name"]
        spec = item.get("spec", {})
        status = item.get("status", {})
        result[name] = {
            "desired": int(spec.get("replicas", 0) or 0),
            "available": int(status.get("availableReplicas", 0) or 0),
            "ready": int(status.get("readyReplicas", 0) or 0),
        }
    return result


def up_values(expected: dict[str, int] | None = None) -> dict[str, float]:
    """Return the worst current sample per job, waiting for a transition.

    Prometheus can briefly retain the previous target sample while a scenario
    is being reconciled. Taking the minimum across matching instances catches
    a deliberately down exporter, while the retry loop lets a newly started
    exporter publish its first scrape before scoring.
    """
    values: dict[str, float] = {}
    for _ in range(12):
        for job in ("node", "blackbox"):
            rows = prometheus_query(f'up{{job="{job}"}}', retries=2)
            values[job] = min((float(row["value"][1]) for row in rows), default=0.0)
        if expected is None or all(values.get(job) == float(value) for job, value in expected.items()):
            return values
        time.sleep(2)
    return values


def probe_value() -> float:
    rows = prometheus_query('probe_success{instance="http://127.0.0.1:19999/health"}')
    return float(rows[0]["value"][1]) if rows else 0.0


def prometheus_alerts(expected: list[str], retries: int = 50) -> dict[str, str]:
    """Wait for expected alert names and return their current states."""
    last: dict[str, str] = {}
    url = f"{PROM_URL}/api/v1/alerts"
    for attempt in range(retries):
        try:
            with urlopen(url, timeout=8) as response:
                payload = json.load(response)
            rows = payload.get("data", {}).get("alerts", [])
            last = {
                str(row.get("labels", {}).get("alertname")): str(row.get("state", ""))
                for row in rows
                if row.get("labels", {}).get("alertname")
            }
            if all(last.get(name) == "firing" for name in expected):
                return last
        except (OSError, URLError, ValueError):
            pass
        if attempt + 1 < retries:
            time.sleep(2)
    return last


def load_cases() -> list[dict]:
    return [json.loads(line) for line in CASE_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(case: dict) -> dict:
    scenario = case["scenario"]
    started = time.monotonic()
    loaded = run(["bash", str(LOADER), scenario], timeout=300)
    checks: list[dict] = [{"name": "scenario_load", "passed": loaded.returncode == 0}]
    details: dict = {"loader_stdout": loaded.stdout[-4000:], "loader_stderr": loaded.stderr[-2000:]}

    try:
        actual = deployment_replicas()
        details["deployments"] = actual
        for name, expected in case["expected_replicas"].items():
            got = actual.get(name, {}).get("desired", 0)
            available = actual.get(name, {}).get("available", 0)
            # A zero-replica failure is valid; a running component must also be available.
            passed = got == expected and (expected == 0 or available >= expected)
            checks.append({"name": f"replicas:{name}", "expected": expected, "actual": got, "available": available, "passed": passed})

        if case.get("expected_up") is not None:
            try:
                observed_up = up_values(case["expected_up"])
                details["up"] = observed_up
                for job, expected in case["expected_up"].items():
                    checks.append({"name": f"up:{job}", "expected": expected, "actual": observed_up.get(job, 0), "passed": observed_up.get(job, 0) == expected})
            except Exception as exc:
                details["prometheus_error"] = str(exc)
                for job in case["expected_up"]:
                    checks.append({"name": f"up:{job}", "expected": case["expected_up"][job], "passed": False})

        if case.get("expected_probe_success") is not None:
            try:
                probe = probe_value()
                details["probe_success"] = probe
                expected = case["expected_probe_success"]
                checks.append({"name": "probe_success:failed-target", "expected": expected, "actual": probe, "passed": probe == expected})
            except Exception as exc:
                details["prometheus_error"] = str(exc)
                checks.append({"name": "probe_success:failed-target", "expected": case["expected_probe_success"], "passed": False})

        if case.get("expected_alerts"):
            expected_alerts = [str(name) for name in case["expected_alerts"]]
            observed_alerts = prometheus_alerts(expected_alerts)
            details["alerts"] = observed_alerts
            for alert_name in expected_alerts:
                checks.append({
                    "name": f"alert:{alert_name}",
                    "expected": "firing",
                    "actual": observed_alerts.get(alert_name),
                    "passed": observed_alerts.get(alert_name) == "firing",
                })
    except Exception as exc:
        details["cluster_error"] = str(exc)

    passed = sum(1 for check in checks if check["passed"])
    result = {
        "id": case["id"],
        "scenario": scenario,
        "score": round(100 * passed / len(checks), 2) if checks else 0.0,
        "passed_checks": passed,
        "total_checks": len(checks),
        "checks": checks,
        "details": details,
        "duration_seconds": round(time.monotonic() - started, 2),
    }
    print(f"{scenario:24} {result['score']:6.2f}% ({passed}/{len(checks)})")
    return result


def main() -> int:
    cases = load_cases()
    results: list[dict] = []
    try:
        for case in cases:
            results.append(evaluate(case))
    finally:
        # Leave the local cluster usable for the next test run.
        restore = run(["bash", str(LOADER), "healthy"], timeout=300)
        if restore.returncode:
            print("WARNING: failed to restore healthy scenario:", restore.stderr[-1000:])

    total_passed = sum(item["passed_checks"] for item in results)
    total_checks = sum(item["total_checks"] for item in results)
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cases": len(results),
        "score": round(100 * total_passed / total_checks, 2) if total_checks else 0.0,
        "passed_checks": total_passed,
        "total_checks": total_checks,
        "results": results,
    }
    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"k8s_scenario_eval_{stamp}.json"
    out_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Overall K8s scenario score: {summary['score']:.2f}% ({total_passed}/{total_checks})")
    print(f"Result: {out_file}")
    return 0 if summary["score"] == 100 else 1


if __name__ == "__main__":
    raise SystemExit(main())
