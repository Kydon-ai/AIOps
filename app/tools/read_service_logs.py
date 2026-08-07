"""受控 systemd 服务日志读取工具。"""

import subprocess

from langchain_core.tools import tool
from loguru import logger

from app.config import config


@tool
def read_service_logs(
    service_name: str,
    minutes: int = 15,
    max_lines: int = 200,
) -> str:
    """读取配置白名单中的 HTTP 服务最近日志，用于告警诊断。

    只允许读取 MANAGED_HTTP_SERVICES 中的服务，使用 journalctl，不执行 shell。
    """
    unit = config.managed_http_services.get(service_name.strip())
    if not unit:
        return f"服务不在白名单中: {service_name}"

    minutes = max(1, min(minutes, 1440))
    max_lines = max(20, min(max_lines, 500))
    try:
        result = subprocess.run(
            [
                "journalctl",
                "--no-pager",
                "--output=short-iso",
                "--unit",
                unit,
                "--since",
                f"{minutes} minutes ago",
                "--lines",
                str(max_lines),
            ],
            capture_output=True,
            text=True,
            timeout=config.service_log_timeout,
            check=False,
        )
        output = (result.stdout or result.stderr).strip()
        if result.returncode != 0:
            return f"读取日志失败: {output}"
        logger.info("读取服务日志: {}，{} 分钟，{} 行", service_name, minutes, len(output.splitlines()))
        return output or "最近没有日志"
    except FileNotFoundError:
        return "当前环境没有 journalctl"
    except subprocess.TimeoutExpired:
        return "读取服务日志超时"
    except Exception as exc:
        logger.exception("读取服务日志失败")
        return f"读取服务日志失败: {exc}"

