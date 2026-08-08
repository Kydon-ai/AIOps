"""自动巡查、告警唤醒和运维报告服务。"""

import asyncio
import hashlib
import json
from textwrap import dedent

from loguru import logger

from app.config import config
from app.services.operation_memory_service import operation_memory_service
from app.services.rag_agent_service import rag_agent_service
from app.tools.query_metrics_alerts import query_prometheus_alerts_api


class AutomationService:
    """以后台任务实现三种运行方式中的定时巡查和告警唤醒。"""

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._active_alerts: set[str] = set()
        self._run_lock = asyncio.Lock()

    async def start(self) -> None:
        if not config.automation_enabled:
            logger.info("自动运维未启用")
            return
        if self._tasks:
            return

        self._tasks = [
            asyncio.create_task(self._alert_watch_loop(), name="alert-watch"),
            asyncio.create_task(self._patrol_loop(), name="hourly-patrol"),
        ]
        logger.info(
            "自动运维已启动: 告警轮询={}秒，定时巡查={}秒",
            config.automation_alert_poll_interval,
            config.automation_patrol_interval,
        )

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("自动运维已停止")

    async def _alert_watch_loop(self) -> None:
        while True:
            try:
                await self.check_alerts_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("告警轮询失败: {}", exc)
            await asyncio.sleep(max(10, config.automation_alert_poll_interval))

    async def _patrol_loop(self) -> None:
        # 启动后先做一次检查，之后按配置周期执行。
        await asyncio.sleep(5)
        while True:
            try:
                await self.run_patrol_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("定时巡查失败: {}", exc)
            await asyncio.sleep(max(60, config.automation_patrol_interval))

    @staticmethod
    def _alert_fingerprint(alert: dict) -> str:
        labels = alert.get("labels") or {}
        raw = json.dumps(labels, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

    async def check_alerts_once(self) -> None:
        """轮询当前告警；新进入 firing 的告警只处理一次。"""
        result, error = await asyncio.to_thread(query_prometheus_alerts_api)
        if error:
            logger.warning("获取 Prometheus 告警失败: {}", error)
            return

        alerts = (result.get("data") or {}).get("alerts") or []
        firing_alerts = {
            self._alert_fingerprint(alert)
            for alert in alerts
            if alert.get("state") == "firing"
        }

        new_alerts = [
            alert
            for alert in alerts
            if alert.get("state") == "firing"
            and self._alert_fingerprint(alert) not in self._active_alerts
        ]
        self._active_alerts = firing_alerts

        for alert in new_alerts:
            await self.handle_alert(alert)

    async def handle_alert(self, alert: dict) -> str:
        """处理一个新告警：读取 Skill、检查日志、必要时执行受控修复。"""
        labels = alert.get("labels") or {}
        alert_name = str(labels.get("alertname") or "unknown-alert")
        fingerprint = self._alert_fingerprint(alert)
        services = ", ".join(sorted(config.managed_http_services)) or "未配置"
        prompt = dedent(
            f"""
            这是一次自动告警唤醒任务，请诊断并在安全范围内处理告警。

            告警数据：
            {json.dumps(alert, ensure_ascii=False, indent=2)}

            执行要求：
            1. 先调用 read_skill，尝试读取与告警名称对应的 Skill：{alert_name}。
            2. 根据 Skill 和告警证据调用 read_service_logs 检查日志；允许的服务名为：{services}。
            3. 判断根因，不要只复述告警。
            4. 只有当 Skill 明确要求、服务在白名单中且 service_restart_enabled 已开启时，才可调用 restart_systemd_service。
            5. 重启后必须重新检查告警或健康状态，并说明重启前后的结果。
            6. 如果没有对应 Skill、没有足够证据或修复风险不明确，只诊断和给出建议，不要猜测或执行重启。
            7. 最后输出：告警摘要、证据、根因判断、已执行动作、验证结果、后续建议。
            """
        ).strip()

        async with self._run_lock:
            answer = await rag_agent_service.query(
                prompt,
                session_id=f"automation-alert-{fingerprint}",
            )
            operation_memory_service.save_operation_report(
                "alert_diagnosis",
                f"告警诊断_{alert_name}",
                answer,
            )
        logger.info("告警自动诊断完成: {}", alert_name)
        return answer

    async def run_patrol_once(self) -> str:
        """执行一次定时巡查，默认只读不修改服务器。"""
        services = ", ".join(sorted(config.managed_http_services)) or "未配置"
        prompt = dedent(
            f"""
            这是一次定时服务器巡查任务，不要重启服务或修改服务器。

            请完成：
            1. 调用 query_prometheus_alerts 获取当前 pending/firing 告警。
            2. 使用 query_prometheus_metrics 检查 CPU、内存、磁盘、targets 和应用健康状态。
            3. 对已配置服务读取最近日志；允许的服务名为：{services}。
            4. 总结健康状态、异常证据、潜在风险和建议。
            5. 如果没有告警，也要明确报告当前没有发现活动告警。
            """
        ).strip()

        async with self._run_lock:
            answer = await rag_agent_service.query(
                prompt,
                session_id="automation-hourly-patrol",
            )
            operation_memory_service.save_operation_report(
                "hourly_patrol",
                "定时服务器巡查",
                answer,
            )
        logger.info("定时服务器巡查完成")
        return answer


automation_service = AutomationService()
