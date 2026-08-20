"""Linux 内存诊断正式工具。

这些工具只读取当前主机的内存、进程和内核日志，不接受任意 shell 命令，
因此可以被生产 Agent 和真实评测共同使用。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

from langchain_core.tools import tool


COMMAND_TIMEOUT = 10
OOM_PATTERN = re.compile(r"oom|out of memory|killed process", re.IGNORECASE)


def _run_fixed_command(args: list[str]) -> tuple[int, str, str]:
    """执行固定参数命令，避免把用户输入拼接进 shell。"""
    executable = shutil.which(args[0])
    if not executable:
        return 127, "", f"当前环境没有找到 {args[0]} 命令"
    try:
        result = subprocess.run(
            [executable, *args[1:]],
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "命令执行超时"
    except OSError as exc:
        return 126, "", str(exc)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


@tool
def get_memory_summary() -> str:
    """读取 Linux 内存和 Swap 总览，等价于固定命令 `free -h`。"""
    code, output, error = _run_fixed_command(["free", "-h"])
    return json.dumps(
        {
            "success": code == 0,
            "command": "free -h",
            "output": output,
            "error": error if code else "",
        },
        ensure_ascii=False,
    )


@tool
def get_top_memory_processes() -> str:
    """读取内存占用最高的进程，固定执行 `ps aux --sort=-%mem`。"""
    code, output, error = _run_fixed_command(["ps", "aux", "--sort=-%mem"])
    lines = output.splitlines()[:10]
    return json.dumps(
        {
            "success": code == 0,
            "command": "ps aux --sort=-%mem | head -10",
            "processes": "\n".join(lines),
            "error": error if code else "",
        },
        ensure_ascii=False,
    )


@tool
def get_oom_events() -> str:
    """读取内核 OOM 证据；没有权限时必须保留 permission denied 事实。"""
    code, output, error = _run_fixed_command(["dmesg", "-T"])
    if code != 0:
        return json.dumps(
            {
                "success": False,
                "command": 'dmesg -T | grep -Ei "oom|out of memory|killed process"',
                "error": error or output or f"dmesg 返回码 {code}",
                "permission_likely": "permission denied" in (error or output).lower(),
            },
            ensure_ascii=False,
        )
    matches = [line for line in output.splitlines() if OOM_PATTERN.search(line)]
    return json.dumps(
        {
            "success": True,
            "command": 'dmesg -T | grep -Ei "oom|out of memory|killed process"',
            "matched": bool(matches),
            "output": "\n".join(matches) if matches else "未发现匹配的 OOM 日志",
        },
        ensure_ascii=False,
    )

