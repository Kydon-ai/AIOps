"""Read-only process inspection tool for Linux servers."""

import json
import shutil
import subprocess

from langchain_core.tools import tool
from loguru import logger


@tool
def get_top_cpu_processes() -> str:
    """获取 CPU 占用最高的前 20 个 Linux 进程。

    固定执行等价于 `ps aux --sort=-%cpu | head -20` 的只读检查，
    不接受外部命令、参数或 Shell 输入。
    """
    ps_path = shutil.which("ps")
    if not ps_path:
        return json.dumps(
            {"success": False, "error": "当前环境没有找到 ps 命令"},
            ensure_ascii=False,
        )

    try:
        result = subprocess.run(
            [ps_path, "aux", "--sort=-%cpu"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {"success": False, "error": "获取进程列表超时"},
            ensure_ascii=False,
        )
    except OSError as exc:
        logger.error("获取进程列表失败: {}", exc)
        return json.dumps(
            {"success": False, "error": f"无法执行 ps: {exc}"},
            ensure_ascii=False,
        )

    if result.returncode != 0:
        return json.dumps(
            {
                "success": False,
                "error": result.stderr.strip() or f"ps 返回码: {result.returncode}",
            },
            ensure_ascii=False,
        )

    lines = result.stdout.splitlines()[:20]
    return json.dumps(
        {
            "success": True,
            "command": "ps aux --sort=-%cpu | head -20",
            "processes": "\n".join(lines),
        },
        ensure_ascii=False,
    )
