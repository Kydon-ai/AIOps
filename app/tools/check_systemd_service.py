"""只读检查 systemd 服务是否存在及当前状态。"""

import json
import re
import shutil
import subprocess

from langchain_core.tools import tool


SERVICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@:-]+$")


def _normalize_unit(service_name: str) -> str:
    name = service_name.strip()
    if not name or not SERVICE_NAME_PATTERN.fullmatch(name):
        raise ValueError("服务名只能包含字母、数字、点、下划线、@、冒号或短横线")
    return name if name.endswith(".service") else f"{name}.service"


@tool
def check_systemd_service(service_name: str) -> str:
    """只读检查指定 systemd 服务是否存在及其当前状态。"""
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return json.dumps(
            {"success": False, "exists": False, "error": "当前环境没有 systemctl"},
            ensure_ascii=False,
        )

    try:
        unit = _normalize_unit(service_name)
    except (AttributeError, ValueError) as exc:
        return json.dumps(
            {"success": False, "exists": False, "error": str(exc)},
            ensure_ascii=False,
        )

    try:
        result = subprocess.run(
            [
                systemctl,
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
    except subprocess.TimeoutExpired:
        return json.dumps(
            {"success": False, "unit": unit, "exists": False, "error": "查询 systemd 服务超时"},
            ensure_ascii=False,
        )
    except OSError as exc:
        return json.dumps(
            {"success": False, "unit": unit, "exists": False, "error": str(exc)},
            ensure_ascii=False,
        )

    properties: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value

    exists = result.returncode == 0 and properties.get("LoadState") not in {None, "not-found"}
    return json.dumps(
        {
            "success": result.returncode == 0,
            "exists": exists,
            "service": service_name,
            "unit": unit,
            "load_state": properties.get("LoadState", "unknown"),
            "active_state": properties.get("ActiveState", "unknown"),
            "sub_state": properties.get("SubState", "unknown"),
            "unit_file_state": properties.get("UnitFileState", "unknown"),
            "error": result.stderr.strip() if result.returncode != 0 else "",
        },
        ensure_ascii=False,
    )
