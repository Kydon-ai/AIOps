"""Controlled restart of an explicitly allowlisted systemd service."""

import json
import os
import subprocess
import time

from langchain_core.tools import tool
from loguru import logger

from app.config import config


def _managed_services() -> dict[str, str]:
    """读取正式白名单；评测场景策略只能收紧权限，不能伪造工具结果。"""
    services = config.managed_http_services
    policy_file = os.getenv("SERVICE_POLICY_FILE", "").strip()
    if policy_file:
        try:
            with open(policy_file, encoding="utf-8") as handle:
                services = json.load(handle).get("managed_http_services", services)
        except (OSError, json.JSONDecodeError, AttributeError):
            services = {}
    return {str(name): str(unit) for name, unit in services.items()}


def _service_unit(service_name: str) -> str | None:
    """从当前正式白名单解析服务单元。"""
    return _managed_services().get(service_name.strip())


def _manager(unit: str) -> list[str]:
    probe = subprocess.run(["systemctl", "show", unit, "--no-pager", "--property=LoadState"], capture_output=True, text=True, timeout=config.service_restart_timeout, check=False)
    return ["systemctl", "--user"] if probe.returncode != 0 or "LoadState=not-found" in probe.stdout else ["systemctl"]


@tool
def restart_systemd_service(service_name: str) -> str:
    """重启白名单中的 systemd 服务并返回重启后的 active 状态。"""
    if not config.service_restart_enabled:
        return json.dumps({"success": False, "error": "服务重启功能未启用"}, ensure_ascii=False)
    unit = _service_unit(service_name)
    if not unit:
        return json.dumps({"success": False, "error": f"服务不在白名单中: {service_name}", "allowed_services": sorted(_managed_services())}, ensure_ascii=False)
    try:
        manager = _manager(unit)
        restart = subprocess.run([*manager, "restart", unit], capture_output=True, text=True, timeout=config.service_restart_timeout, check=False)
        if restart.returncode != 0:
            return json.dumps({"success": False, "service": service_name, "unit": unit, "error": (restart.stderr or restart.stdout).strip()}, ensure_ascii=False)
        # systemd reports active as soon as it has spawned the process. Give a
        # real HTTP service a short readiness window before returning so the
        # required post-restart health check cannot observe a startup race.
        # 让 systemd 的 ActiveState、进程监听和 HTTP 服务有机会收敛，
        # 这样紧跟其后的正式复核不会读到启动竞态。
        time.sleep(2.5)
        status = subprocess.run([*manager, "is-active", unit], capture_output=True, text=True, timeout=config.service_restart_timeout, check=False)
        active = status.stdout.strip()
        logger.warning("controlled restart: {} ({}) -> {}", service_name, unit, active)
        return json.dumps({"success": status.returncode == 0, "service": service_name, "unit": unit, "scope": "user" if "--user" in manager else "system", "status": active}, ensure_ascii=False)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
