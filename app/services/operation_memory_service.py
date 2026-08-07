"""将对话与自动运维结果沉淀为可检索的知识记录。"""

import re
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger

from app.config import config


class OperationMemoryService:
    """写入 Markdown 记录，并复用现有向量索引服务写入 RAG。"""

    def __init__(self) -> None:
        self._index_lock = threading.Lock()

    def _safe_name(self, value: str, fallback: str) -> str:
        name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())
        return (name.strip("._") or fallback)[:100]

    def _index(self, path: Path) -> None:
        try:
            # 延迟导入，避免服务模块初始化时扩大循环依赖。
            from app.services.vector_index_service import vector_index_service

            with self._index_lock:
                vector_index_service.index_single_file(str(path))
            logger.info("运维记录已写入 RAG: {}", path)
        except Exception as exc:
            # 记录文件仍然保留，后续可以重新索引；不阻塞主对话或自动巡查。
            logger.error("运维记录写入 RAG 失败: {}", exc)

    def save_conversation(self, session_id: str, question: str, answer: str) -> Path:
        """保存用户对话，并更新该会话对应的 RAG 文档。"""
        root = Path(config.operation_records_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"conversation_{self._safe_name(session_id, 'default')}.md"

        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        addition = (
            f"\n## 对话记录 {timestamp}\n\n"
            f"### 用户问题\n\n{question.strip()}\n\n"
            f"### Agent 回答\n\n{answer.strip()}\n"
        )
        # 防止一个长期会话无限膨胀；最近记录对排障通常最有价值。
        content = (existing + addition)[-200_000:]
        path.write_text(
            f"# 用户运维对话\n\n会话: {session_id}\n{content}",
            encoding="utf-8",
        )
        if config.auto_index_conversations:
            self._index(path)
        return path

    def save_operation_report(self, kind: str, title: str, report: str) -> Path:
        """保存一次定时巡查或告警诊断报告，并写入 RAG。"""
        root = Path(config.operation_records_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone()
        filename = (
            f"{timestamp.strftime('%Y%m%d_%H%M%S')}_"
            f"{self._safe_name(kind, 'operation')}_"
            f"{self._safe_name(title, 'report')}.md"
        )
        path = root / filename
        content = (
            f"# {title}\n\n"
            f"- 类型: {kind}\n"
            f"- 时间: {timestamp.isoformat(timespec='seconds')}\n\n"
            f"{report.strip()}\n"
        )
        path.write_text(content, encoding="utf-8")
        self._index(path)
        return path


operation_memory_service = OperationMemoryService()
