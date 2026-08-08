"""Read-only Linux disk usage inspection tools."""

import json
import shutil
import subprocess
from pathlib import Path

from langchain_core.tools import tool
from loguru import logger


COMMAND_TIMEOUT = 30


@tool
def get_disk_filesystems() -> str:
    """查看 Linux 文件系统的类型、容量、已用空间和挂载点。

    固定执行只读命令 `df -hT`，不接受外部命令或参数。
    """
    df_path = shutil.which("df")
    if not df_path:
        return json.dumps(
            {"success": False, "error": "当前环境没有找到 df 命令"},
            ensure_ascii=False,
        )

    try:
        result = subprocess.run(
            [df_path, "-hT"],
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {"success": False, "error": "获取文件系统使用情况超时"},
            ensure_ascii=False,
        )
    except OSError as exc:
        logger.error("执行 df 失败: {}", exc)
        return json.dumps(
            {"success": False, "error": f"无法执行 df: {exc}"},
            ensure_ascii=False,
        )

    output = result.stdout.strip()
    if result.returncode != 0:
        return json.dumps(
            {
                "success": False,
                "command": "df -hT",
                "error": result.stderr.strip() or f"df 返回码: {result.returncode}",
            },
            ensure_ascii=False,
        )

    logger.info("获取文件系统使用情况成功")
    return json.dumps(
        {"success": True, "command": "df -hT", "output": output},
        ensure_ascii=False,
    )


@tool
def get_directory_disk_usage(mountpoint: str) -> str:
    """查看指定目录下第一层目录的磁盘占用，并按大小排序。

    执行等价于 `du -xhd1 <mountpoint> 2>/dev/null | sort -h`。
    目录参数仅作为子进程参数传入，不会拼接到 Shell 命令中。
    """
    if not isinstance(mountpoint, str) or not mountpoint.strip():
        return json.dumps(
            {"success": False, "error": "mountpoint 必须是非空目录路径"},
            ensure_ascii=False,
        )

    directory = Path(mountpoint.strip()).expanduser()
    try:
        directory = directory.resolve(strict=True)
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        return json.dumps(
            {"success": False, "mountpoint": mountpoint, "error": f"目录不可用: {exc}"},
            ensure_ascii=False,
        )

    if not directory.is_dir():
        return json.dumps(
            {"success": False, "mountpoint": str(directory), "error": "mountpoint 不是目录"},
            ensure_ascii=False,
        )

    du_path = shutil.which("du")
    sort_path = shutil.which("sort")
    if not du_path or not sort_path:
        return json.dumps(
            {"success": False, "error": "当前环境缺少 du 或 sort 命令"},
            ensure_ascii=False,
        )

    try:
        du_result = subprocess.run(
            [du_path, "-xhd1", str(directory)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
        sort_result = subprocess.run(
            [sort_path, "-h"],
            input=du_result.stdout,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {
                "success": False,
                "mountpoint": str(directory),
                "error": "目录占用统计超时",
            },
            ensure_ascii=False,
        )
    except OSError as exc:
        logger.error("执行 du 失败: {}", exc)
        return json.dumps(
            {"success": False, "mountpoint": str(directory), "error": f"无法执行 du: {exc}"},
            ensure_ascii=False,
        )

    output = sort_result.stdout.strip()
    # 与 `du ... 2>/dev/null | sort -h` 保持一致：du 可能因个别无权限
    # 子目录返回非零，但只要 sort 成功，仍返回它已经统计到的结果。
    if sort_result.returncode != 0 or not output:
        return json.dumps(
            {
                "success": False,
                "mountpoint": str(directory),
                "error": "目录占用统计失败",
            },
            ensure_ascii=False,
        )

    logger.info("获取目录占用成功: {}", directory)
    return json.dumps(
        {
            "success": True,
            "mountpoint": str(directory),
            "command": f"du -xhd1 {directory} 2>/dev/null | sort -h",
            "output": output,
        },
        ensure_ascii=False,
    )
