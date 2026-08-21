"""Read-only inspection and policy-controlled systemd MCP tools."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from mcp.server.fastmcp import FastMCP

from app.config import config
from app.tools.systemd_policy import (
    RESTARTABLE_STATES,
    resolve_service,
)


SERVICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@:-]+$")

mcp = FastMCP(
    "systemd-service",
    instructions=(
        "提供只读 systemd 状态检查，以及受白名单/灰名单和鉴权保护的 restart/stop。"
        "灰名单优先匹配，仅用于明确授权的测试服务。"
    ),
    host=os.getenv("SYSTEMD_MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("SYSTEMD_MCP_PORT", "8006")),
    streamable_http_path="/mcp",
)


def _systemctl() -> str:
    executable = shutil.which("systemctl")
    if not executable:
        raise FileNotFoundError("当前环境没有 systemctl")
    return executable


def _normalize_unit(service_name: str) -> str:
    name = str(service_name or "").strip()
    if not name or not SERVICE_NAME_PATTERN.fullmatch(name):
        raise ValueError("service_name contains invalid characters")
    return name if name.endswith(".service") else f"{name}.service"


def _inspect(service_name: str) -> dict[str, object]:
    unit = _normalize_unit(service_name)
    result = subprocess.run(
        [
            _systemctl(),
            "show",
            unit,
            "--no-pager",
            "--property=Id,LoadState,ActiveState,SubState,UnitFileState",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    properties: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value
    exists = result.returncode == 0 and properties.get("LoadState") not in {None, "not-found"}
    return {
        "success": result.returncode == 0,
        "exists": exists,
        "service": service_name,
        "unit": unit,
        "load_state": properties.get("LoadState", "unknown"),
        "active_state": properties.get("ActiveState", "unknown"),
        "sub_state": properties.get("SubState", "unknown"),
        "unit_file_state": properties.get("UnitFileState", "unknown"),
        "error": result.stderr.strip() if result.returncode != 0 else "",
    }


def _error(message: str, **extra: object) -> str:
    return json.dumps({"success": False, "error": message, **extra}, ensure_ascii=False)


@mcp.tool()
def check_systemd_service(service_name: str) -> str:
    """Read-only check of systemd existence and current state."""
    try:
        return json.dumps(_inspect(service_name), ensure_ascii=False)
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired, OSError) as exc:
        return _error(str(exc), exists=False, service=service_name)


def _resolve_for_action(service_name: str) -> dict[str, str] | None:
    # resolve_service checks greylist before the normal allowlist.
    return resolve_service(service_name)


@mcp.tool()
def restart_systemd_service(service_name: str) -> str:
    """Restart a configured service after a greylist/allowlist policy check."""
    if not config.service_restart_enabled:
        return _error("service_restart_disabled")

    resolved = _resolve_for_action(service_name)
    if not resolved:
        return _error(f"service_not_configured: {service_name}")
    source = resolved["source"]
    try:
        inspection = _inspect(resolved["unit"])
        inspection["source"] = source
        if not inspection["exists"]:
            inspection.update(success=False, restarted=False, action="skipped", reason="service_not_found")
            return json.dumps(inspection, ensure_ascii=False)

        active_state = str(inspection.get("active_state", "unknown")).strip().lower()
        if active_state == "active":
            inspection.update(success=True, restarted=False, action="skipped", reason="service_already_active")
            return json.dumps(inspection, ensure_ascii=False)
        if active_state not in RESTARTABLE_STATES:
            inspection.update(
                success=False,
                restarted=False,
                action="skipped",
                reason="status_not_restartable",
            )
            return json.dumps(inspection, ensure_ascii=False)

        restart = subprocess.run(
            [_systemctl(), "restart", resolved["unit"]],
            capture_output=True,
            text=True,
            timeout=config.service_restart_timeout,
            check=False,
        )
        if restart.returncode != 0:
            return _error(
                (restart.stderr or restart.stdout).strip() or "systemctl restart failed",
                service=service_name,
                unit=resolved["unit"],
                source=source,
            )

        after = _inspect(resolved["unit"])
        after["source"] = source
        after["success"] = after.get("active_state") == "active"
        after["restarted"] = True
        after["action"] = "restarted"
        return json.dumps(after, ensure_ascii=False)
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired, OSError) as exc:
        return _error(str(exc), service=service_name, source=source)


@mcp.tool()
def stop_systemd_service(service_name: str) -> str:
    """Stop an active greylist test service after a policy check."""
    if not config.service_stop_enabled:
        return _error("service_stop_disabled")

    resolved = _resolve_for_action(service_name)
    if not resolved:
        return _error(f"service_not_configured: {service_name}")
    if resolved["source"] != "greylist":
        return _error(
            "stop_requires_greylist_service",
            service=service_name,
            unit=resolved["unit"],
            source=resolved["source"],
        )

    try:
        inspection = _inspect(resolved["unit"])
        inspection["source"] = "greylist"
        if not inspection["exists"]:
            inspection.update(success=False, stopped=False, action="skipped", reason="service_not_found")
            return json.dumps(inspection, ensure_ascii=False)

        active_state = str(inspection.get("active_state", "unknown")).strip().lower()
        if active_state != "active":
            inspection.update(success=True, stopped=False, action="skipped", reason="service_not_active")
            return json.dumps(inspection, ensure_ascii=False)

        stop = subprocess.run(
            [_systemctl(), "stop", resolved["unit"]],
            capture_output=True,
            text=True,
            timeout=config.service_restart_timeout,
            check=False,
        )
        if stop.returncode != 0:
            return _error(
                (stop.stderr or stop.stdout).strip() or "systemctl stop failed",
                service=service_name,
                unit=resolved["unit"],
                source="greylist",
            )

        after = _inspect(resolved["unit"])
        after["source"] = "greylist"
        after_state = str(after.get("active_state", "unknown")).lower()
        stopped = after_state in {"inactive", "dead", "failed"}
        after["success"] = stopped
        after["stopped"] = stopped
        after["action"] = "stopped" if stopped else "stop_not_confirmed"
        return json.dumps(after, ensure_ascii=False)
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired, OSError) as exc:
        return _error(str(exc), service=service_name, source="greylist")


if __name__ == "__main__":
    mcp.run(transport=os.getenv("SYSTEMD_MCP_TRANSPORT", "streamable-http"))
