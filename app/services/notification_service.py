"""将自动运维报告发送到后端配置的 Webhook。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from app.config import config


class NotificationService:
    """负责构造飞书兼容卡片并发送，不让通知失败影响自动运维主流程。"""

    @staticmethod
    def _limit_report(report: str, max_chars: int = 28_000) -> str:
        """限制卡片正文长度，避免 Webhook 平台因消息过大拒收。"""
        text = str(report or "").strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n> 报告过长，正文已截断；完整报告保存在后端报告文件中。"

    @staticmethod
    def _build_payload(
        *,
        title: str,
        report: str,
        kind: str,
        report_path: str = "",
        alert: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造与示例一致的飞书 interactive markdown 卡片。"""
        labels = (alert or {}).get("labels") or {}
        metadata = [
            f"- 类型: {kind}",
            f"- 时间: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        ]
        if labels.get("alertname"):
            metadata.append(f"- 告警名称: {labels['alertname']}")
        if labels.get("severity"):
            metadata.append(f"- 严重性: {labels['severity']}")
        if report_path:
            metadata.append(f"- 完整报告: `{report_path}`")
        content = f"# {title}\n\n" + "\n".join(metadata) + "\n\n" + NotificationService._limit_report(report)
        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "elements": [{"tag": "markdown", "content": content}],
            },
        }

    async def send_report(
        self,
        *,
        title: str,
        report: str,
        kind: str,
        report_path: str = "",
        alert: dict[str, Any] | None = None,
    ) -> bool:
        """发送报告；未配置地址或发送失败时只记录日志并返回 False。"""
        if not config.notification_enabled:
            logger.info("报告通知未启用，跳过发送")
            return False
        webhook_url = config.webhook_url.strip()
        if not webhook_url:
            logger.debug("未配置 WEBHOOK_URL，跳过报告通知")
            return False

        payload = self._build_payload(
            title=title,
            report=report,
            kind=kind,
            report_path=report_path,
            alert=alert,
        )
        try:
            async with httpx.AsyncClient(timeout=config.webhook_timeout) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
                body = response.json() if response.content else {}
            if isinstance(body, dict) and body.get("code") not in (None, 0):
                logger.warning("Webhook 返回业务失败: code={}, msg={}", body.get("code"), body.get("msg"))
                return False
            logger.info("运维报告已发送到 Webhook: {}", title)
            return True
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("运维报告 Webhook 发送失败: {}", exc)
            return False


notification_service = NotificationService()
