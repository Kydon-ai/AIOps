"""Controlled stop for explicitly configured greylist test services."""

from __future__ import annotations

import json
import subprocess

from langchain_core.tools import tool

from app.config import config
from app.tools.systemd_policy import (
    active_state,
    resolve_service,
    systemd_manager,
)


def _error(message: str, **extra: object) -> str:
    return json.dumps({"success": False, "error": message, **extra}, ensure_ascii=False)


@tool
def stop_systemd_service(service_name: str) -> str:
    """Stop an active greylist test service after a policy check.

    The stop action intentionally does not operate on the normal production
    allowlist. It is limited to greylisted test services and requires
    SERVICE_STOP_ENABLED=true.
    """
    if not config.service_stop_enabled:
        return _error("service_stop_disabled")

    resolved = resolve_service(service_name)
    if not resolved:
        return _error(f"service_not_configured: {service_name}")
    if resolved["source"] != "greylist":
        return _error(
            "stop_requires_greylist_service",
            service=service_name,
            unit=resolved["unit"],
            source=resolved["source"],
        )

    unit = resolved["unit"]
    try:
        manager = systemd_manager(unit)
        before, before_result = active_state(manager, unit)
        scope = "user" if "--user" in manager else "system"
        base = {
            "service": service_name,
            "unit": unit,
            "scope": scope,
            "source": "greylist",
            "status": before or "unknown",
        }
        if before != "active":
            return json.dumps(
                {
                    "success": True,
                    **base,
                    "stopped": False,
                    "action": "skipped",
                    "reason": "service_not_active",
                    "detail": (before_result.stderr or before_result.stdout).strip(),
                },
                ensure_ascii=False,
            )

        stop = subprocess.run(
            [*manager, "stop", unit],
            capture_output=True,
            text=True,
            timeout=config.service_restart_timeout,
            check=False,
        )
        if stop.returncode != 0:
            return _error(
                (stop.stderr or stop.stdout).strip() or "systemctl stop failed",
                service=service_name,
                unit=unit,
                scope=scope,
                source="greylist",
            )

        after, after_result = active_state(manager, unit)
        stopped = after in {"inactive", "dead", "failed"}
        return json.dumps(
            {
                "success": stopped,
                **base,
                "status": after or "unknown",
                "stopped": stopped,
                "action": "stopped" if stopped else "stop_not_confirmed",
                "detail": (after_result.stderr or after_result.stdout).strip() if not stopped else "",
            },
            ensure_ascii=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return _error(str(exc), service=service_name, unit=unit, source="greylist")
