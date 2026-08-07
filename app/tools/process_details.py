"""Read-only process detail tool for Linux servers."""

import json
import shutil
import subprocess

from langchain_core.tools import tool
from loguru import logger


PROCESS_FORMAT = (
    "pid,ppid,user,group,stat,pri,ni,pcpu,pmem,vsz,rss,lstart,etime,time,args"
)


@tool
def get_process_details(pid: int) -> str:
    """根据 PID 查询 Linux 进程的详细运行信息。

    固定执行等价于：
    `ps -p <pid> -o pid,ppid,user,group,stat,pri,ni,pcpu,pmem,vsz,rss,lstart,etime,time,args`
    不接受额外命令参数或 Shell 输入。
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return json.dumps(
            {"success": False, "error": "pid 必须是正整数"},
            ensure_ascii=False,
        )

    ps_path = shutil.which("ps")
    if not ps_path:
        return json.dumps(
            {"success": False, "error": "当前环境没有找到 ps 命令"},
            ensure_ascii=False,
        )

    try:
        result = subprocess.run(
            [ps_path, "-p", str(pid), "-o", PROCESS_FORMAT],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {"success": False, "error": "查询进程详情超时", "pid": pid},
            ensure_ascii=False,
        )
    except OSError as exc:
        logger.error("查询进程详情失败: {}", exc)
        return json.dumps(
            {"success": False, "error": f"无法执行 ps: {exc}", "pid": pid},
            ensure_ascii=False,
        )

    output = result.stdout.strip()
    if result.returncode != 0 or len(output.splitlines()) <= 1:
        return json.dumps(
            {
                "success": False,
                "pid": pid,
                "error": output or result.stderr.strip() or "未找到该进程",
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "success": True,
            "pid": pid,
            "command": f"ps -p {pid} -o {PROCESS_FORMAT}",
            "process": output,
        },
        ensure_ascii=False,
    )
