"""只读 Linux 内存诊断 MCP 服务。

启动：
    uv run python -m app.mcp_servers.memory_diagnostics

默认监听 127.0.0.1:8005/mcp，避免把服务器诊断接口直接暴露到公网。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from mcp.server.fastmcp import FastMCP


COMMAND_TIMEOUT = 10
OOM_PATTERN = re.compile(r"oom|out of memory|killed process", re.IGNORECASE)

mcp = FastMCP(
    "memory-diagnostics",
    instructions=(
        "只读 Linux 内存诊断服务。按 free、top memory processes、OOM logs 的顺序采集证据；"
        "不提供杀进程、清理内存、修改配置或重启服务能力。"
    ),
    host=os.getenv("MEMORY_MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MEMORY_MCP_PORT", "8005")),
    streamable_http_path="/mcp",
)


def _run_fixed_command(args: list[str]) -> tuple[int, str, str]:
    """执行固定命令参数，不经过 Shell。"""
    executable = shutil.which(args[0])
    if not executable:
        raise FileNotFoundError(f"当前环境没有找到 {args[0]} 命令")

    result = subprocess.run(
        [executable, *args[1:]],
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT,
        check=False,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


@mcp.tool()
def get_memory_summary() -> str:
    """获取 Linux 内存和 Swap 总览，固定执行 `free -h`。"""
    try:
        return_code, output, error = _run_fixed_command(["free", "-h"])
        if return_code != 0:
            return json.dumps(
                {"success": False, "command": "free -h", "error": error or f"返回码: {return_code}"},
                ensure_ascii=False,
            )
        return json.dumps(
            {"success": True, "command": "free -h", "output": output},
            ensure_ascii=False,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"success": False, "error": "free -h 执行超时"}, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def get_top_memory_processes() -> str:
    """获取内存占用最高的 Linux 进程，固定执行 `ps aux --sort=-%mem | head`。"""
    try:
        return_code, output, error = _run_fixed_command(["ps", "aux", "--sort=-%mem"])
        if return_code != 0:
            return json.dumps(
                {
                    "success": False,
                    "command": "ps aux --sort=-%mem | head",
                    "error": error or f"返回码: {return_code}",
                },
                ensure_ascii=False,
            )
        lines = output.splitlines()[:10]
        return json.dumps(
            {
                "success": True,
                "command": "ps aux --sort=-%mem | head",
                "output": "\n".join(lines),
            },
            ensure_ascii=False,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"success": False, "error": "进程内存排行执行超时"}, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def get_oom_events() -> str:
    """查询内核 OOM 证据，固定执行等价于 `dmesg -T | grep -Ei ...`。"""
    try:
        return_code, output, error = _run_fixed_command(["dmesg", "-T"])
        if return_code != 0:
            return json.dumps(
                {
                    "success": False,
                    "command": 'dmesg -T | grep -Ei "oom|out of memory|killed process"',
                    "error": error or f"dmesg 返回码: {return_code}",
                    "permission_likely": "permission denied" in error.lower(),
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
    except subprocess.TimeoutExpired:
        return json.dumps({"success": False, "error": "OOM 日志查询执行超时"}, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport=os.getenv("MEMORY_MCP_TRANSPORT", "streamable-http"))
