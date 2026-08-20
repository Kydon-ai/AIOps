"""Read-only Kubernetes inspection tools used by the K8s evaluation mode."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from typing import Any

from langchain_core.tools import tool


DEFAULT_NAMESPACE = "observability"
COMMAND_TIMEOUT = 20


def _run_kubectl(args: list[str], timeout: int = COMMAND_TIMEOUT) -> tuple[dict[str, Any] | None, str | None]:
    """Run kubectl without a shell; fall back to the K3s wrapper if needed."""
    commands = [["kubectl", *args], ["sudo", "k3s", "kubectl", *args]]
    errors: list[str] = []
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            errors.append(f"command not found: {command[0]}")
            continue
        except subprocess.TimeoutExpired:
            return None, f"kubectl command timed out after {timeout}s"

        if completed.returncode == 0:
            try:
                return json.loads(completed.stdout), None
            except json.JSONDecodeError as exc:
                return None, f"kubectl returned invalid JSON: {exc}"
        errors.append((completed.stderr or completed.stdout).strip()[-800:])
    return None, "; ".join(error for error in errors if error) or "kubectl command failed"


def _result(payload: Any = None, error: str | None = None) -> str:
    if error:
        return json.dumps({"success": False, "error": error}, ensure_ascii=False)
    return json.dumps({"success": True, "data": payload}, ensure_ascii=False)


def _namespace(value: str) -> str:
    value = (value or DEFAULT_NAMESPACE).strip()
    return value[:63] or DEFAULT_NAMESPACE


def _selector(value: str) -> str:
    """兼容常见 app= 写法，同时映射到本项目真实 K8s 标签。"""
    selector = (value or "").strip()[:200]
    if selector.startswith("app=") and "," not in selector and "=" not in selector[4:]:
        return f"app.kubernetes.io/name={selector[4:]}"
    return selector


@tool
def get_kubernetes_deployments(namespace: str = DEFAULT_NAMESPACE) -> str:
    """Read desired, ready and available replica counts for deployments."""
    namespace = _namespace(namespace)
    payload, error = _run_kubectl(["-n", namespace, "get", "deployments", "-o", "json"])
    if error:
        return _result(error=error)
    deployments = []
    for item in (payload or {}).get("items", []):
        spec = item.get("spec") or {}
        status = item.get("status") or {}
        deployments.append(
            {
                "name": item.get("metadata", {}).get("name"),
                "desired_replicas": spec.get("replicas", 0),
                "ready_replicas": status.get("readyReplicas", 0),
                "available_replicas": status.get("availableReplicas", 0),
                "updated_replicas": status.get("updatedReplicas", 0),
                "conditions": status.get("conditions", []),
            }
        )
    return _result({"namespace": namespace, "deployments": deployments})


@tool
def get_kubernetes_pods(namespace: str = DEFAULT_NAMESPACE, label_selector: str = "") -> str:
    """Read Pod phase, readiness, restart count and node placement."""
    namespace = _namespace(namespace)
    args = ["-n", namespace, "get", "pods", "-o", "json"]
    if label_selector.strip():
        args.extend(["-l", _selector(label_selector)])
    payload, error = _run_kubectl(args)
    if error:
        return _result(error=error)
    pods = []
    for item in (payload or {}).get("items", []):
        status = item.get("status") or {}
        containers = status.get("containerStatuses") or []
        pods.append(
            {
                "name": item.get("metadata", {}).get("name"),
                "phase": status.get("phase"),
                "node": item.get("spec", {}).get("nodeName"),
                "pod_ip": status.get("podIP"),
                "restarts": sum(int(c.get("restartCount", 0) or 0) for c in containers),
                "containers": [
                    {
                        "name": c.get("name"),
                        "ready": c.get("ready", False),
                        "restart_count": c.get("restartCount", 0),
                        "state": c.get("state", {}),
                        "last_state": c.get("lastState", {}),
                    }
                    for c in containers
                ],
            }
        )
    return _result({"namespace": namespace, "pods": pods})


@tool
def get_kubernetes_events(namespace: str = DEFAULT_NAMESPACE, limit: int = 50) -> str:
    """Read recent Kubernetes events, newest first."""
    namespace = _namespace(namespace)
    payload, error = _run_kubectl(["-n", namespace, "get", "events", "-o", "json"])
    if error:
        return _result(error=error)
    events = []
    for item in (payload or {}).get("items", []):
        metadata = item.get("metadata") or {}
        involved = item.get("involvedObject") or {}
        events.append(
            {
                "last_timestamp": item.get("lastTimestamp") or metadata.get("creationTimestamp"),
                "type": item.get("type"),
                "reason": item.get("reason"),
                "message": item.get("message"),
                "object": f"{involved.get('kind', '')}/{involved.get('name', '')}",
                "count": item.get("count", 1),
            }
        )
    events.sort(key=lambda event: event.get("last_timestamp") or "", reverse=True)
    return _result({"namespace": namespace, "events": events[: max(1, min(int(limit), 200))]})


@tool
def get_kubernetes_pod_logs(
    pod_name: str,
    namespace: str = DEFAULT_NAMESPACE,
    container: str = "",
    tail_lines: int = 200,
) -> str:
    """Read recent logs from a named Pod; this tool never mutates the cluster."""
    namespace = _namespace(namespace)
    pod_name = (pod_name or "").strip()[:253]
    if not pod_name:
        return _result(error="pod_name cannot be empty")
    args = ["-n", namespace, "logs", pod_name, "--timestamps=true", f"--tail={max(1, min(int(tail_lines), 1000))}"]
    if container.strip():
        args.extend(["-c", container.strip()[:63]])
    commands = [["kubectl", *args], ["sudo", "k3s", "kubectl", *args]]
    errors: list[str] = []
    for command in commands:
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=COMMAND_TIMEOUT, check=False)
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            return _result(error=f"kubectl logs timed out after {COMMAND_TIMEOUT}s")
        if completed.returncode == 0:
            return _result({"namespace": namespace, "pod": pod_name, "container": container or None, "logs": completed.stdout[-50_000:]})
        errors.append((completed.stderr or completed.stdout).strip()[-800:])
    return _result(error="; ".join(error for error in errors if error) or "kubectl logs failed")


@tool
def get_kubernetes_nodes() -> str:
    """Read Kubernetes node readiness and allocatable capacity."""
    payload, error = _run_kubectl(["get", "nodes", "-o", "json"])
    if error:
        return _result(error=error)
    nodes = []
    for item in (payload or {}).get("items", []):
        status = item.get("status") or {}
        nodes.append(
            {
                "name": item.get("metadata", {}).get("name"),
                "conditions": status.get("conditions", []),
                "capacity": status.get("capacity", {}),
                "allocatable": status.get("allocatable", {}),
            }
        )
    return _result({"nodes": nodes})


__all__ = [
    "get_kubernetes_deployments",
    "get_kubernetes_pods",
    "get_kubernetes_events",
    "get_kubernetes_pod_logs",
    "get_kubernetes_nodes",
]
