"""受控 HTTP 服务重启工具。"""

import json
import subprocess

from langchain_core.tools import tool
from loguru import logger

from app.config import config


def _service_unit(service_name: str) -> str | None:
    """只允许重启配置白名单中的 systemd unit。"""
    return config.managed_http_services.get(service_name.strip())


@tool
def restart_http_service(service_name: str) -> str:
    """重启一个配置白名单中的 HTTP systemd 服务并检查状态。

    该工具不会执行任意 shell 命令。服务必须先配置在
    MANAGED_HTTP_SERVICES 中，并且 SERVICE_RESTART_ENABLED=true。
    自动修复前必须先读取对应 Skill 并完成证据检查。
    """
    if not config.service_restart_enabled:
        return json.dumps(
            {"success": False, "error": "服务重启功能未启用"},
            ensure_ascii=False,
        )

    unit = _service_unit(service_name)
    if not unit:
        return json.dumps(
            {
                "success": False,
                "error": f"服务不在白名单中: {service_name}",
                "allowed_services": sorted(config.managed_http_services),
            },
            ensure_ascii=False,
        )

    try:
        restart = subprocess.run(
            ["systemctl", "restart", unit],
            capture_output=True,
            text=True,
            timeout=config.service_restart_timeout,
            check=False,
        )
        if restart.returncode != 0:
            return json.dumps(
                {
                    "success": False,
                    "service": service_name,
                    "unit": unit,
                    "error": (restart.stderr or restart.stdout).strip(),
                },
                ensure_ascii=False,
            )

        status = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=config.service_restart_timeout,
            check=False,
        )
        active = status.stdout.strip()
        logger.warning("自动重启服务: {} ({})，状态: {}", service_name, unit, active)
        return json.dumps(
            {
                "success": status.returncode == 0,
                "service": service_name,
                "unit": unit,
                "status": active,
            },
            ensure_ascii=False,
        )
    except FileNotFoundError:
        return json.dumps(
            {"success": False, "error": "当前环境没有 systemctl"},
            ensure_ascii=False,
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {"success": False, "error": "重启服务超时"},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("重启服务失败")
        return json.dumps(
            {"success": False, "error": str(exc)},
            ensure_ascii=False,
        )

