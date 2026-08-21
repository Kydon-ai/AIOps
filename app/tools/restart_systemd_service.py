"""Controlled restart of an explicitly configured systemd service."""

from __future__ import annotations

import json
import subprocess
import time

from langchain_core.tools import tool
from loguru import logger

from app.config import config
from app.tools.systemd_policy import (
    RESTARTABLE_STATES,
    active_state,
    allowed_service_names,
    resolve_service,
    systemd_manager,
)


def _error(message: str, **extra: object) -> str:
    return json.dumps({"success": False, "error": message, **extra}, ensure_ascii=False)


@tool
def restart_systemd_service(service_name: str) -> str:
    """Restart a configured systemd service after a state and policy check.

    Greylist services are resolved before the normal allowlist. They are
    intended for test scenarios; the current-state safety guard still skips an
    unnecessary restart of an active service.
    """
    if not config.service_restart_enabled:
        return _error("service_restart_disabled")

    resolved = resolve_service(service_name)
    if not resolved:
        return _error(
            f"service_not_configured: {service_name}",
            allowed_services=allowed_service_names(),
        )

    source = resolved["source"]
    unit = resolved["unit"]
    try:
        manager = systemd_manager(unit)
        active, before = active_state(manager, unit)
        scope = "user" if "--user" in manager else "system"
        base = {
            "service": service_name,
            "unit": unit,
            "scope": scope,
            "source": source,
            "status": active or "unknown",
        }
        if active == "active":
            logger.info("controlled restart skipped: {} ({}) is already active", service_name, unit)
            return json.dumps(
                {
                    "success": True,
                    **base,
                    "restarted": False,
                    "action": "skipped",
                    "reason": "service_already_active",
                },
                ensure_ascii=False,
            )
        if active not in RESTARTABLE_STATES:
            return json.dumps(
                {
                    "success": False,
                    **base,
                    "restarted": False,
                    "action": "skipped",
                    "reason": "status_not_restartable",
                    "detail": (before.stderr or before.stdout).strip() or "service state is not restartable",
                },
                ensure_ascii=False,
            )

        restart = subprocess.run(
            [*manager, "restart", unit],
            capture_output=True,
            text=True,
            timeout=config.service_restart_timeout,
            check=False,
        )
        if restart.returncode != 0:
            return _error(
                (restart.stderr or restart.stdout).strip() or "systemctl restart failed",
                service=service_name,
                unit=unit,
                scope=scope,
                source=source,
            )

        # Give systemd and a real HTTP process a short convergence window.
        time.sleep(2.5)
        after, status = active_state(manager, unit)
        logger.warning("controlled restart: {} ({}) -> {}", service_name, unit, after)
        return json.dumps(
            {
                "success": status.returncode == 0 and after == "active",
                **base,
                "status": after or "unknown",
                "restarted": True,
                "action": "restarted",
            },
            ensure_ascii=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return _error(str(exc), service=service_name, unit=unit, source=source)
