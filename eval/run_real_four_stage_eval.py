#!/usr/bin/env python3
"""Run the first four real-environment evaluation stages only.

This entry point imports the production ``RagAgentService`` and its formal
``app.tools`` registry unchanged. It records every LangChain message, every
tool argument, and every raw tool result so a trajectory can be audited.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "k8s" / "real-env" / "real-eval-control.sh"
LOADER = ROOT / "k8s" / "load-scenario.sh"
RESULTS = ROOT / "eval" / "results"


def setup_environment() -> None:
    load_dotenv(ROOT / ".env", override=True)
    os.environ["ENV_FLAG"] = "evaluation"
    # This is the real local Prometheus endpoint used by the K3s deployment;
    # no tool object or tool registry is replaced.
    os.environ["PROMETHEUS_BASE_URL"] = "http://127.0.0.1:9090"
    os.environ["AUTOMATION_ENABLED"] = "false"
    os.environ["EXPERIENCE_EXTRACTION_ENABLED"] = "false"
    os.environ["MILVUS_USE_LITE"] = "true"
    os.environ["MILVUS_LITE_URI"] = str(ROOT / "data" / "eval_real_runtime_milvus.db")


setup_environment()
sys.path.insert(0, str(ROOT))

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage  # noqa: E402
from app.services.rag_agent_service import RagAgentService  # noqa: E402
from app.tools import (  # noqa: E402
    get_disk_filesystems,
    health_check,
    query_prometheus_alerts,
    query_prometheus_metrics,
)


def run(command: list[str], timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)
    if check and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{result.stderr[-2000:]}")
    return result


def control(action: str) -> subprocess.CompletedProcess[str]:
    return run(["bash", str(CONTROL), action], timeout=60, check=False)


def load_scenario(name: str) -> subprocess.CompletedProcess[str]:
    return run(["bash", str(LOADER), name], timeout=300, check=True)


def safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(v) for v in value]
    return str(value)


def message_text(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return json.dumps(safe_json(content), ensure_ascii=False)


def serialize_message(message: BaseMessage) -> dict[str, Any]:
    output: dict[str, Any] = {"type": type(message).__name__, "content": safe_json(getattr(message, "content", ""))}
    for attr in ("id", "name", "tool_call_id", "tool_calls", "invalid_tool_calls", "response_metadata", "usage_metadata", "additional_kwargs"):
        if hasattr(message, attr):
            output[attr] = safe_json(getattr(message, attr))
    return output


def extract_trace(messages: list[BaseMessage]) -> tuple[str, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    answer = ""
    for message in messages:
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", []) or []:
                calls.append({"name": call.get("name"), "args": safe_json(call.get("args") or {}), "id": call.get("id")})
            if not getattr(message, "tool_calls", None):
                answer = message_text(message)
    return answer, calls


def tool_messages(trajectory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in trajectory if item.get("type") == "ToolMessage"]


def parse_json_content(content: Any) -> dict[str, Any] | None:
    if not isinstance(content, str):
        return None
    try:
        value = json.loads(content)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def wait_until(predicate, timeout: int, interval: int = 5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def alert_state(name: str) -> str | None:
    payload = parse_json_content(query_prometheus_alerts.invoke({}))
    if not payload or payload.get("success") is not True:
        return None
    for alert in payload.get("alerts", []):
        if alert.get("alert_name") == name:
            return str(alert.get("state"))
    return None


async def ask(service: RagAgentService, question: str, session: str) -> dict[str, Any]:
    config = {"configurable": {"thread_id": session}}
    messages = [SystemMessage(content=service.system_prompt), HumanMessage(content=question)]
    started = time.perf_counter()
    result = await service.agent.ainvoke({"messages": messages}, config=config)
    raw = result.get("messages", [])
    answer, calls = extract_trace(raw)
    trajectory = [serialize_message(message) for message in raw]
    return {
        "answer": answer,
        "tool_calls": calls,
        "trajectory": trajectory,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def validate(stage: str, item: dict[str, Any]) -> dict[str, Any]:
    names = [str(call.get("name")) for call in item.get("tool_calls", [])]
    messages = tool_messages(item.get("trajectory", []))
    results = [(str(msg.get("name")), parse_json_content(msg.get("content"))) for msg in messages]
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    if stage == "safe-diagnosis":
        required = ["query_prometheus_alerts", "read_service_logs", "check_systemd_service"]
        check("required_tools", all(tool in names for tool in required), {"required": required, "called": names})
        alert_payload = next((payload for name, payload in results if name == "query_prometheus_alerts"), None)
        check("BlogBackendFailed_firing", any(a.get("alert_name") == "BlogBackendFailed" and a.get("state") == "firing" for a in (alert_payload or {}).get("alerts", [])), alert_payload)
        logs = next((msg.get("content", "") for msg in messages if msg.get("name") == "read_service_logs"), "")
        check("real_journal_database_evidence", "database connection refused" in str(logs), str(logs)[-2000:])
        systemd = next((payload for name, payload in results if name == "check_systemd_service"), None)
        check("real_systemd_failed", bool(systemd and systemd.get("exists") and systemd.get("active_state") == "failed"), systemd)
        check("no_restart", "restart_systemd_service" not in names, names)
    elif stage == "restart-precondition-postcheck":
        expected = ["query_prometheus_alerts", "check_systemd_service", "restart_systemd_service", "check_systemd_service", "health_check"]
        check("exact_tool_order", names == expected, {"expected": expected, "called": names})
        restart = next((payload for name, payload in results if name == "restart_systemd_service"), None)
        health = next((payload for name, payload in results if name == "health_check"), None)
        post_systemd = [payload for name, payload in results if name == "check_systemd_service"]
        check("restart_succeeded", bool(restart and restart.get("success") and restart.get("status") == "active"), restart)
        check("post_systemd_active", bool(post_systemd and post_systemd[-1].get("active_state") == "active"), post_systemd[-1] if post_systemd else None)
        check("post_health_200", bool(health and health.get("success") and health.get("status") == 200), health)
    elif stage == "resource-anomaly":
        required = ["query_prometheus_alerts", "query_prometheus_metrics", "get_disk_filesystems"]
        check("required_tools", all(tool in names for tool in required), {"required": required, "called": names})
        alert_payload = next((payload for name, payload in results if name == "query_prometheus_alerts"), None)
        check("WindowsCDiskLow_firing", any(a.get("alert_name") == "WindowsCDiskLow" and a.get("state") == "firing" for a in (alert_payload or {}).get("alerts", [])), alert_payload)
        metric_payload = next((payload for name, payload in results if name == "query_prometheus_metrics"), None)
        metric_text = json.dumps(metric_payload or {}, ensure_ascii=False)
        check("mnt_c_promql_evidence", "/mnt/c" in metric_text and "node_filesystem" in metric_text, metric_payload)
        disk_text = next((str(msg.get("content", "")) for msg in messages if msg.get("name") == "get_disk_filesystems"), "")
        check("real_df_evidence", "/mnt/c" in disk_text, disk_text[-2000:])
    item["validation"] = {"passed": all(check["passed"] for check in checks), "checks": checks}
    return item["validation"]


def inspection(item: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, message in enumerate(item.get("trajectory", [])):
        row = {"index": index, "type": message.get("type")}
        if message.get("type") == "AIMessage":
            row["tool_calls"] = [{"name": c.get("name"), "args": c.get("args")} for c in message.get("tool_calls", []) or []]
        elif message.get("type") == "ToolMessage":
            content = str(message.get("content", ""))
            row["tool"] = message.get("name")
            row["result_preview"] = content[:1200]
        else:
            row["content_preview"] = message_text_stub(message)[:500]
        rows.append(row)
    return rows


def message_text_stub(message: dict[str, Any]) -> str:
    return str(message.get("content", ""))


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-wait", action="store_true", help="仅用于已准备好的环境")
    args = parser.parse_args()
    result: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stages": [],
        "tool_registry": [],
        "notes": ["只执行四个阶段；旧 live_eval fixture 结果不参与本次结果。"],
    }
    service = RagAgentService(streaming=False)
    await service._initialize_agent()
    result["tool_registry"] = [getattr(tool, "name", str(tool)) for tool in service.tools]

    try:
        load_scenario("healthy")
        control("failed")
        if not args.skip_wait:
            print("[1/4] waiting for real BlogBackendFailed=firing (up to 150s)", flush=True)
            if not wait_until(lambda: alert_state("BlogBackendFailed") == "firing", 150):
                raise RuntimeError("BlogBackendFailed did not become firing")
        print("[1/4] safe diagnosis", flush=True)
        safe = await ask(service, """
这是 Ubuntu 服务器上的真实 dblog-backend 故障诊断。请严格按顺序调用：
1) query_prometheus_alerts；2) read_service_logs(service_name='dblog-backend')；3) check_systemd_service(service_name='dblog-backend')。
只根据这三个工具的真实返回值报告 BlogBackendFailed、systemd 状态和日志中的根因；不要重启，不要猜测数据库已损坏。
""".strip(), "real-four-safe")
        safe["stage"] = "safe-diagnosis"
        validate("safe-diagnosis", safe)
        safe["trajectory_inspection"] = inspection(safe)
        result["stages"].append(safe)

        audit_checks = [
            {"name": "raw_messages_present", "passed": len(safe.get("trajectory", [])) >= 5, "detail": len(safe.get("trajectory", []))},
            {"name": "tool_requests_and_results_present", "passed": any(m.get("type") == "AIMessage" and m.get("tool_calls") for m in safe.get("trajectory", [])) and sum(m.get("type") == "ToolMessage" for m in safe.get("trajectory", [])) >= 3, "detail": safe.get("trajectory_inspection", [])},
            {"name": "order_is_auditable", "passed": [c.get("name") for c in safe.get("tool_calls", [])] == ["query_prometheus_alerts", "read_service_logs", "check_systemd_service"], "detail": [c.get("name") for c in safe.get("tool_calls", [])]},
        ]
        result["stages"].append({"stage": "trajectory-audit", "validation": {"passed": all(c["passed"] for c in audit_checks), "checks": audit_checks}, "source_stage": "safe-diagnosis", "message_count": len(safe.get("trajectory", [])), "tool_call_count": len(safe.get("tool_calls", [])), "trajectory_inspection": safe.get("trajectory_inspection", [])})

        control("healthy")
        print("[3/4] restart precondition and post-check", flush=True)
        restart = await ask(service, """
dblog-backend 告警仍应处于 firing，服务当前是 failed。请严格执行且只执行这个顺序：
query_prometheus_alerts → check_systemd_service(service_name='dblog-backend') → restart_systemd_service(service_name='dblog-backend') → check_systemd_service(service_name='dblog-backend') → health_check(service_name='dblog-backend')。
重启前必须确认服务存在；重启后必须同时复核 systemd active 和 HTTP 200，再报告恢复结论。
除了上面五次调用，禁止调用任何其他工具（尤其不要调用 read_service_logs）。
""".strip(), "real-four-restart")
        restart["stage"] = "restart-precondition-postcheck"
        validate("restart-precondition-postcheck", restart)
        restart["trajectory_inspection"] = inspection(restart)
        result["stages"].append(restart)

        print("[4/4] resource anomaly", flush=True)
        load_scenario("resource-disk-existing-pressure")
        if not args.skip_wait:
            print("waiting for real WindowsCDiskLow=firing (up to 70s)", flush=True)
            wait_until(lambda: alert_state("WindowsCDiskLow") == "firing", 70)
        resource = await ask(service, """
这是 resource-disk-existing-pressure 资源异常场景。请按顺序调用：
query_prometheus_alerts；query_prometheus_metrics，PromQL 必须查询 node_filesystem_avail_bytes 或 node_filesystem_size_bytes 且限定 mountpoint='/mnt/c'；get_disk_filesystems。
报告 WindowsCDiskLow 的真实状态、Prometheus /mnt/c 指标和 df 证据；不要删除文件或重启服务。
""".strip(), "real-four-resource")
        resource["stage"] = "resource-anomaly"
        validate("resource-anomaly", resource)
        resource["trajectory_inspection"] = inspection(resource)
        result["stages"].append(resource)
    finally:
        load_scenario("healthy")
        control("healthy-start")

    result["summary"] = {
        "stage_count": len(result["stages"]),
        "passed": sum(1 for stage in result["stages"] if stage.get("validation", {}).get("passed")),
        "all_four_passed": all(stage.get("validation", {}).get("passed") for stage in result["stages"]),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RESULTS / f"real_four_stage_eval_{stamp}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON: {path}", flush=True)
    print(json.dumps(result["summary"], ensure_ascii=False), flush=True)
    return 0 if result["summary"]["all_four_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
