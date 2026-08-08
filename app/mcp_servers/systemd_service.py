"""只读检查和白名单 systemd 重启 MCP 服务。

默认监听 127.0.0.1:8006/mcp。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from mcp.server.fastmcp import FastMCP

from app.config import config


SERVICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@:-]+$")

mcp = FastMCP(
    "systemd-service",
    instructions=(
        "提供只读 systemd 服务检查和受白名单保护的重启能力。"
        "处理 BlogBackendFailed 时必须先检查服务存在，再执行重启。"
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
    name = service_name.strip()
    if not name or not SERVICE_NAME_PATTERN.fullmatch(name):
        raise ValueError("服务名只能包含字母、数字、点、下划线、@、冒号或短横线")
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


def _configured_unit(service_name: str) -> str | None:
    name = service_name.strip()
    configured = config.managed_http_services
    if name in configured:
        return configured[name]
    if name.endswith(".service") and name.removesuffix(".service") in configured:
        return configured[name.removesuffix(".service")]
    for unit in configured.values():
        if unit == name or unit == f"{name}.service":
            return unit
    return None


@mcp.tool()
def check_systemd_service(service_name: str) -> str:
    """只读检查 systemd 服务是否存在及当前状态。"""
    try:
        return json.dumps(_inspect(service_name), ensure_ascii=False)
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired, OSError) as exc:
        return json.dumps(
            {"success": False, "exists": False, "service": service_name, "error": str(exc)},
            ensure_ascii=False,
        )


@mcp.tool()
def restart_systemd_service(service_name: str) -> str:
    """重启配置白名单中的 systemd 服务，并返回重启后的状态。"""
    if not config.service_restart_enabled:
        return json.dumps(
            {"success": False, "error": "服务重启功能未启用"},
            ensure_ascii=False,
        )

    configured_unit = _configured_unit(service_name)
    if not configured_unit:
        return json.dumps(
            {
                "success": False,
                "error": f"服务不在白名单中: {service_name}",
                "allowed_services": sorted(config.managed_http_services),
            },
            ensure_ascii=False,
        )

    try:
        inspection = _inspect(configured_unit)
        if not inspection["exists"]:
            inspection.update(success=False, error="systemd 服务不存在，未执行重启")
            return json.dumps(inspection, ensure_ascii=False)

        restart = subprocess.run(
            [_systemctl(), "restart", configured_unit],
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
                    "unit": configured_unit,
                    "error": (restart.stderr or restart.stdout).strip(),
                },
                ensure_ascii=False,
            )

        after = _inspect(configured_unit)
        after["success"] = after["active_state"] == "active"
        after["restarted"] = True
        return json.dumps(after, ensure_ascii=False)
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired, OSError) as exc:
        return json.dumps(
            {"success": False, "service": service_name, "error": str(exc)},
            ensure_ascii=False,
        )


if __name__ == "__main__":
    mcp.run(transport=os.getenv("SYSTEMD_MCP_TRANSPORT", "streamable-http"))
