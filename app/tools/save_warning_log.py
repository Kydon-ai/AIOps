"""Tool for persisting warning reports to the local warning log directory."""

import json
import re
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool
from loguru import logger

from app.config import config

MAX_WARNING_BYTES = 2 * 1024 * 1024


def _safe_warning_type(value: str) -> str:
    """将警告类型转换为安全的文件名片段。"""
    safe = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", value.strip())
    safe = re.sub(r"\s+", "_", safe)
    safe = safe.strip(" ._")
    return safe[:100] or "warning"


@tool
def save_warning_log(text_content: str, warning_type: str) -> str:
    """将警告文本落盘到 ./data/warnning_log/YYYY-mm-DD_HH-MM-SS_<警告类型>.md。"""
    if not isinstance(text_content, str) or not text_content.strip():
        return json.dumps(
            {"success": False, "error": "text_content 不能为空"},
            ensure_ascii=False,
        )
    if not isinstance(warning_type, str) or not warning_type.strip():
        return json.dumps(
            {"success": False, "error": "warning_type 不能为空"},
            ensure_ascii=False,
        )

    content = text_content.strip()
    content_size = len(content.encode("utf-8"))
    if content_size > MAX_WARNING_BYTES:
        return json.dumps(
            {
                "success": False,
                "error": f"警告内容不能超过 {MAX_WARNING_BYTES} 字节",
            },
            ensure_ascii=False,
        )

    try:
        warning_log_dir = Path(config.warning_logs_dir).expanduser().resolve()
        warning_log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        warning_name = _safe_warning_type(warning_type)
        base_name = f"{timestamp}_{warning_name}"
        path = warning_log_dir / f"{base_name}.md"

        # 同一秒内出现同类告警时避免覆盖已有记录。
        suffix = 1
        while path.exists():
            path = warning_log_dir / f"{base_name}_{suffix}.md"
            suffix += 1

        path.write_text(content + "\n", encoding="utf-8")
        logger.info("警告记录已落盘: {}", path)
        return json.dumps(
            {
                "success": True,
                "path": str(path),
                "filename": path.name,
                "warning_type": warning_type.strip(),
                "size": content_size,
            },
            ensure_ascii=False,
        )
    except OSError as exc:
        logger.error("警告记录落盘失败: {}", exc)
        return json.dumps(
            {"success": False, "error": f"警告记录落盘失败: {exc}"},
            ensure_ascii=False,
        )
