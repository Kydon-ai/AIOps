"""Read-only systemd service inspection for system and user units."""

import json
import re
import shutil
import subprocess

from langchain_core.tools import tool

SERVICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@:-]+$")


def _normalize_unit(service_name: str) -> str:
    name = service_name.strip()
    if not name or not SERVICE_NAME_PATTERN.fullmatch(name):
        raise ValueError("服务名包含不允许的字符")
    return name if name.endswith(".service") else f"{name}.service"


def _show(systemctl: str, unit: str, user: bool) -> subprocess.CompletedProcess[str]:
    command = [systemctl]
    if user:
        command.append("--user")
    command.extend(["show", unit, "--no-pager", "--property=Id,LoadState,ActiveState,SubState,UnitFileState"])
    return subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)


@tool
def check_systemd_service(service_name: str) -> str:
    """只读检查 systemd 服务是否存在及当前状态。"""
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return json.dumps({"success": False, "exists": False, "error": "当前环境没有 systemctl"}, ensure_ascii=False)
    try:
        unit = _normalize_unit(service_name)
    except (AttributeError, ValueError) as exc:
        return json.dumps({"success": False, "exists": False, "error": str(exc)}, ensure_ascii=False)
    try:
        result = _show(systemctl, unit, False)
        scope = "system"
        if result.returncode != 0 or "LoadState=not-found" in result.stdout:
            user_result = _show(systemctl, unit, True)
            if user_result.returncode == 0 and "LoadState=not-found" not in user_result.stdout:
                result = user_result
                scope = "user"
    except subprocess.TimeoutExpired:
        return json.dumps({"success": False, "unit": unit, "exists": False, "error": "查询 systemd 服务超时"}, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({"success": False, "unit": unit, "exists": False, "error": str(exc)}, ensure_ascii=False)
    properties: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value
    exists = result.returncode == 0 and properties.get("LoadState") not in {None, "not-found"}
    return json.dumps({"success": result.returncode == 0, "exists": exists, "service": service_name, "unit": unit, "scope": scope, "load_state": properties.get("LoadState", "unknown"), "active_state": properties.get("ActiveState", "unknown"), "sub_state": properties.get("SubState", "unknown"), "unit_file_state": properties.get("UnitFileState", "unknown"), "error": result.stderr.strip() if result.returncode != 0 else ""}, ensure_ascii=False)
