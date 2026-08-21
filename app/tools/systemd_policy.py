"""Shared policy helpers for controlled systemd actions.

The greylist is deliberately resolved before the normal service allowlist. It
is intended for disposable/test services, but it is not an unrestricted shell
escape: callers still need the relevant action flag and an exact configured
service name.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from app.config import config


RESTARTABLE_STATES = frozenset({"failed", "inactive", "dead"})


def _policy_file() -> dict[str, Any] | None:
    path = os.getenv("SERVICE_POLICY_FILE", "").strip()
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        # A configured policy file is authoritative.  Do not silently fall
        # back to a broader in-process policy when it cannot be read.
        return {"__policy_error__": True}


def _mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(name).strip(): str(unit).strip()
        for name, unit in value.items()
        if str(name).strip() and str(unit).strip()
    }


def service_policies() -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(greylist, allowlist)`` with the greylist taking precedence."""
    policy = _policy_file()
    if policy is None:
        return _mapping(config.managed_http_greylist), _mapping(config.managed_http_services)
    if policy.get("__policy_error__"):
        return {}, {}
    return (
        _mapping(policy.get("managed_http_greylist", config.managed_http_greylist)),
        _mapping(policy.get("managed_http_services", config.managed_http_services)),
    )


def _lookup(mapping: dict[str, str], name: str) -> str | None:
    """Resolve a configured name or its explicit ``.service`` form."""
    if name in mapping:
        return mapping[name]
    short_name = name.removesuffix(".service")
    if short_name in mapping:
        return mapping[short_name]
    normalized = name if name.endswith(".service") else f"{name}.service"
    for configured_name, unit in mapping.items():
        configured_short_name = configured_name.removesuffix(".service")
        if configured_name == normalized or configured_short_name == short_name:
            return unit
    for unit in mapping.values():
        if unit == name or unit == normalized:
            return unit
    return None


def resolve_service(service_name: str) -> dict[str, str] | None:
    """Resolve a service, checking the greylist before the normal allowlist."""
    name = str(service_name or "").strip()
    greylist, allowlist = service_policies()
    unit = _lookup(greylist, name)
    if unit:
        return {"name": name, "unit": unit, "source": "greylist"}
    unit = _lookup(allowlist, name)
    if unit:
        return {"name": name, "unit": unit, "source": "allowlist"}
    return None


def allowed_service_names() -> list[str]:
    greylist, allowlist = service_policies()
    return sorted(set(greylist) | set(allowlist))


def systemd_manager(unit: str) -> list[str]:
    """Select system or user systemd scope without accepting arbitrary units."""
    probe = subprocess.run(
        ["systemctl", "show", unit, "--no-pager", "--property=LoadState"],
        capture_output=True,
        text=True,
        timeout=config.service_restart_timeout,
        check=False,
    )
    return ["systemctl", "--user"] if probe.returncode != 0 or "LoadState=not-found" in probe.stdout else ["systemctl"]


def active_state(manager: list[str], unit: str) -> tuple[str, subprocess.CompletedProcess[str]]:
    result = subprocess.run(
        [*manager, "is-active", unit],
        capture_output=True,
        text=True,
        timeout=config.service_restart_timeout,
        check=False,
    )
    return result.stdout.strip().lower(), result
