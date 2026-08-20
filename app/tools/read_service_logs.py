"""Read journal logs for a managed service."""

import json
import os
import subprocess

from langchain_core.tools import tool
from loguru import logger

from app.config import config


@tool
def read_service_logs(service_name: str, minutes: int = 15, max_lines: int = 200) -> str:
    """读取白名单服务最近的 journal 日志。"""
    services = config.managed_http_services
    policy_file = os.getenv("SERVICE_POLICY_FILE", "").strip()
    if policy_file:
        try:
            with open(policy_file, encoding="utf-8") as handle:
                services = json.load(handle).get("managed_http_services", {})
        except (OSError, json.JSONDecodeError, AttributeError):
            services = {}
    unit = services.get(service_name.strip())
    if not unit:
        return f"服务不在白名单中: {service_name}"
    minutes = max(1, min(minutes, 1440))
    max_lines = max(20, min(max_lines, 500))
    common = ["--no-pager", "--output=short-iso", "--since", f"{minutes} minutes ago", "--lines", str(max_lines)]
    try:
        result = subprocess.run(["journalctl", "--unit", unit, *common], capture_output=True, text=True, timeout=config.service_log_timeout, check=False)
        if result.returncode != 0 or not result.stdout.strip() or result.stdout.strip() == "-- No entries --":
            user_result = subprocess.run(["journalctl", "--user", "--user-unit", unit, *common], capture_output=True, text=True, timeout=config.service_log_timeout, check=False)
            if user_result.returncode == 0 and user_result.stdout.strip():
                result = user_result
        output = (result.stdout or result.stderr).strip()
        if result.returncode != 0:
            return f"读取日志失败: {output}"
        logger.info("读取服务日志: {}", service_name)
        return output or "最近没有日志"
    except FileNotFoundError:
        return "当前环境没有 journalctl"
    except subprocess.TimeoutExpired:
        return "读取服务日志超时"
    except Exception as exc:
        return f"读取服务日志失败: {exc}"
