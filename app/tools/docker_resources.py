"""面向受控 exporter 的 Docker 容器检查与重启工具。"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from langchain_core.tools import tool
from loguru import logger


COMMAND_TIMEOUT = 20
RESTART_TIMEOUT = 60

# 只允许两个监控 exporter 使用 Docker 重启工具，拒绝任意容器名。
SERVICE_ALIASES: dict[str, tuple[str, ...]] = {
    "node_exporter": ("node-exporter", "node_exporter"),
    "blackbox_exporter": ("blackbox-exporter", "blackbox_exporter"),
}


def _normal_service_name(value: str) -> str:
    """把告警常见写法映射到受控服务名。"""
    normalized = str(value or "").strip().lower().replace("-", "_")
    return normalized


def _container_matches(container: dict[str, Any], service_name: str) -> bool:
    """只按受控别名匹配容器名称或镜像名。"""
    aliases = SERVICE_ALIASES.get(service_name, ())
    haystack = " ".join(
        str(container.get(field, "")).lower().replace("/", " ")
        for field in ("Names", "Image")
    )
    return any(alias in haystack for alias in aliases)


def _run_docker_ps() -> tuple[list[dict[str, Any]], str | None]:
    """固定执行 docker ps -a，不接受外部 Shell 或任意参数。"""
    docker = shutil.which("docker")
    if not docker:
        return [], "当前环境没有找到 docker 命令"
    try:
        result = subprocess.run(
            [docker, "ps", "-a", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [], "docker ps -a 执行超时"
    except OSError as exc:
        return [], f"无法执行 docker ps -a: {exc}"

    if result.returncode != 0:
        return [], (result.stderr or result.stdout).strip()[-1000:] or f"docker ps -a 返回码: {result.returncode}"

    containers: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("忽略无法解析的 docker ps 输出行")
            continue
        containers.append(item)
    return containers, None


def _result(payload: Any = None, error: str | None = None, error_code: str | None = None) -> str:
    """统一返回结构化 JSON，保留真实命令结果。"""
    if error:
        data: dict[str, Any] = {"success": False, "error": error, "command": "docker ps -a"}
        if payload is not None:
            data["data"] = payload
        if error_code:
            data["error_code"] = error_code
        return json.dumps(data, ensure_ascii=False)
    return json.dumps({"success": True, "data": payload, "command": "docker ps -a"}, ensure_ascii=False)


@tool
def get_docker_containers(service_name: str = "") -> str:
    """执行受控的 `docker ps -a`，查找 node_exporter 或 blackbox_exporter 容器。"""
    service = _normal_service_name(service_name)
    if service and service not in SERVICE_ALIASES:
        return _result(error=f"不允许检查 Docker 服务: {service_name}", error_code="service_not_allowlisted")
    containers, error = _run_docker_ps()
    if error:
        return _result(error=error, error_code="docker_unavailable")
    matched = [item for item in containers if not service or _container_matches(item, service)]
    return _result(
        {
            "service_name": service or None,
            "total_containers": len(containers),
            "matched_containers": matched,
        }
    )


@tool
def restart_docker_container(service_name: str) -> str:
    """重启唯一匹配的受控 exporter Docker 容器，并返回真实复核状态。"""
    service = _normal_service_name(service_name)
    if service not in SERVICE_ALIASES:
        return _result(error=f"不允许重启 Docker 服务: {service_name}", error_code="service_not_allowlisted")

    docker = shutil.which("docker")
    if not docker:
        return _result(error="当前环境没有找到 docker 命令", error_code="docker_unavailable")
    containers, error = _run_docker_ps()
    if error:
        return _result(error=error, error_code="docker_unavailable")

    matched = [item for item in containers if _container_matches(item, service)]
    if not matched:
        return _result(
            {"service_name": service, "action": "not_found", "matched_containers": []},
            error=f"docker ps -a 中没有找到 {service} 对应容器",
            error_code="container_not_found",
        )
    if len(matched) > 1:
        return _result(
            {"service_name": service, "action": "ambiguous", "matched_containers": matched},
            error=f"找到多个 {service} 容器，拒绝自动选择并重启",
            error_code="multiple_containers",
        )

    container = matched[0]
    name = str(container.get("Names", "")).strip().lstrip("/")
    state = str(container.get("State", "")).strip().lower()
    if not name:
        return _result(error="Docker 容器缺少名称，拒绝重启", error_code="invalid_container")
    if state == "running":
        return _result(
            {"service_name": service, "container": name, "action": "skipped", "state": state},
        )

    try:
        restarted = subprocess.run(
            [docker, "restart", "--time", "10", name],
            capture_output=True,
            text=True,
            timeout=RESTART_TIMEOUT,
            check=False,
        )
        if restarted.returncode != 0:
            return _result(
                {"service_name": service, "container": name, "action": "restart_failed"},
                error=(restarted.stderr or restarted.stdout).strip() or "docker restart 失败",
                error_code="restart_failed",
            )
        status = subprocess.run(
            [docker, "inspect", "--format", "{{.State.Status}}", name],
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
        final_state = status.stdout.strip()
        return _result(
            {
                "service_name": service,
                "container": name,
                "action": "restarted",
                "state": final_state,
                "restart_returncode": restarted.returncode,
            },
            error=None if status.returncode == 0 else (status.stderr or "docker inspect 失败").strip(),
            error_code=None if status.returncode == 0 else "verification_failed",
        )
    except subprocess.TimeoutExpired:
        return _result(
            {"service_name": service, "container": name, "action": "restart_timeout"},
            error="Docker 容器重启或复核超时",
            error_code="timeout",
        )
    except OSError as exc:
        return _result(error=f"无法执行 Docker 重启: {exc}", error_code="docker_error")
