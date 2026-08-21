#!/usr/bin/env python3
"""Run the real Agent against every live K3s scenario.

Unlike ``run_live_eval.py``, this evaluator does not install fixture routers.  The
Agent receives only read-only Kubernetes and Prometheus tools, and every tool
result is captured in the output trajectory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = ROOT / "eval" / "k8s_scenario_cases.jsonl"
LOADER = ROOT / "k8s" / "load-scenario.sh"
RESULTS_DIR = ROOT / "eval" / "results"


def load_eval_environment() -> None:
    """Set local-K3s endpoints before importing app.config or app.tools."""
    load_dotenv(ROOT / ".env")
    os.environ["ENV_FLAG"] = "evaluation"
    os.environ["PROMETHEUS_BASE_URL"] = "http://127.0.0.1:9090"
    os.environ["AUTOMATION_ENABLED"] = "false"
    os.environ["SERVICE_RESTART_ENABLED"] = "false"
    os.environ["EXPERIENCE_EXTRACTION_ENABLED"] = "false"
    os.environ["MILVUS_USE_LITE"] = "true"
    os.environ["MILVUS_LITE_URI"] = str(ROOT / "data" / "eval_k8s_runtime_milvus.db")


load_eval_environment()
sys.path.insert(0, str(ROOT))

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402

from app.tools import (  # noqa: E402
    get_disk_filesystems,
    get_directory_disk_usage,
    get_kubernetes_deployments,
    get_kubernetes_events,
    get_kubernetes_nodes,
    get_kubernetes_pod_logs,
    get_kubernetes_pods,
    query_prometheus_alerts,
    query_prometheus_metrics,
)


K8S_READ_ONLY_TOOLS = (
    get_kubernetes_deployments,
    get_kubernetes_pods,
    get_kubernetes_events,
    get_kubernetes_pod_logs,
    get_kubernetes_nodes,
    query_prometheus_alerts,
    query_prometheus_metrics,
    get_disk_filesystems,
    get_directory_disk_usage,
)


def safe_json(value: Any) -> Any:
    """Convert LangChain message metadata into JSON without dropping evidence."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(item) for item in value]
    return str(value)


def message_content(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict):
                chunks.append(str(block.get("text", block.get("content", ""))))
            else:
                chunks.append(str(block))
        return "".join(chunks)
    return str(content)


def serialize_message(message: BaseMessage) -> dict[str, Any]:
    """Persist both tool requests and tool responses, not only the final answer."""
    output: dict[str, Any] = {
        "type": type(message).__name__,
        "content": safe_json(getattr(message, "content", "")),
    }
    for attribute in (
        "id",
        "name",
        "tool_call_id",
        "tool_calls",
        "invalid_tool_calls",
        "response_metadata",
        "usage_metadata",
        "additional_kwargs",
    ):
        if hasattr(message, attribute):
            output[attribute] = safe_json(getattr(message, attribute))
    return output


def extract_trace(messages: list[BaseMessage]) -> tuple[str, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    answer = ""
    for message in messages:
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", []) or []:
                calls.append(
                    {
                        "name": call.get("name"),
                        "args": safe_json(call.get("args") or {}),
                        "id": call.get("id"),
                    }
                )
            if not getattr(message, "tool_calls", None):
                answer = message_content(message)
    return answer, calls


def load_cases() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in CASE_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_command(command: list[str], timeout: int = 300):
    import subprocess

    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout)


def observe_case(case: dict[str, Any]) -> dict[str, Any]:
    """Read the same live state that the Agent is expected to diagnose."""
    # Importing this module is side-effect free; its helpers use kubectl and the
    # local Prometheus URL configured above.
    from eval.run_k8s_scenario_eval import (
        deployment_replicas,
        prometheus_alerts,
        probe_value,
        up_values,
    )

    checks: list[dict[str, Any]] = []
    details: dict[str, Any] = {}
    actual = deployment_replicas()
    details["deployments"] = actual
    for name, expected in case.get("expected_replicas", {}).items():
        observed = actual.get(name, {})
        got = observed.get("desired", 0)
        available = observed.get("available", 0)
        checks.append(
            {
                "name": f"replicas:{name}",
                "expected": expected,
                "actual": got,
                "available": available,
                "passed": got == expected and (expected == 0 or available >= expected),
            }
        )

    if case.get("expected_up") is not None:
        try:
            observed_up = up_values(case["expected_up"])
            details["up"] = observed_up
            for job, expected in case["expected_up"].items():
                checks.append(
                    {
                        "name": f"up:{job}",
                        "expected": expected,
                        "actual": observed_up.get(job, 0),
                        "passed": observed_up.get(job, 0) == expected,
                    }
                )
        except Exception as exc:
            details["prometheus_error"] = str(exc)
            for job, expected in case["expected_up"].items():
                checks.append({"name": f"up:{job}", "expected": expected, "passed": False})

    if case.get("expected_probe_success") is not None:
        try:
            probe = probe_value()
            details["probe_success"] = probe
            expected = case["expected_probe_success"]
            checks.append(
                {
                    "name": "probe_success:failed-target",
                    "expected": expected,
                    "actual": probe,
                    "passed": probe == expected,
                }
            )
        except Exception as exc:
            details["prometheus_error"] = str(exc)
            checks.append(
                {
                    "name": "probe_success:failed-target",
                    "expected": case["expected_probe_success"],
                    "passed": False,
                }
            )

    if case.get("expected_alerts"):
        expected_alerts = [str(name) for name in case["expected_alerts"]]
        observed_alerts = prometheus_alerts(expected_alerts)
        details["alerts"] = observed_alerts
        for alert_name in expected_alerts:
            checks.append(
                {
                    "name": f"alert:{alert_name}",
                    "expected": "firing",
                    "actual": observed_alerts.get(alert_name),
                    "passed": observed_alerts.get(alert_name) == "firing",
                }
            )

    passed = sum(1 for check in checks if check["passed"])
    return {
        "checks": checks,
        "score": round(100 * passed / len(checks), 2) if checks else 0.0,
        "passed_checks": passed,
        "total_checks": len(checks),
        "details": details,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def required_tools(case: dict[str, Any]) -> list[str]:
    required = ["get_kubernetes_deployments", "get_kubernetes_pods"]
    if case.get("expected_up") is not None or case.get("expected_probe_success") is not None:
        required.append("query_prometheus_metrics")
    if case.get("expected_alerts"):
        required.append("query_prometheus_alerts")
    return required


def tool_score(case: dict[str, Any], calls: list[dict[str, Any]], trajectory: list[dict[str, Any]]) -> dict[str, Any]:
    names = [str(call.get("name")) for call in calls]
    required = required_tools(case)
    successful_by_tool: dict[str, int] = {}
    valid_namespaces: set[str] = set()
    for message in trajectory:
        if message.get("type") != "ToolMessage":
            continue
        name = str(message.get("name") or "")
        try:
            payload = json.loads(str(message.get("content") or ""))
        except (TypeError, json.JSONDecodeError):
            continue
        if name == "get_kubernetes_deployments":
            data = payload.get("data") or {}
            if payload.get("success") is True and data.get("namespace") == "observability":
                valid_namespaces.add("deployments")
                successful_by_tool[name] = successful_by_tool.get(name, 0) + 1
        elif name == "get_kubernetes_pods":
            data = payload.get("data") or {}
            if payload.get("success") is True and data.get("namespace") == "observability":
                valid_namespaces.add("pods")
                successful_by_tool[name] = successful_by_tool.get(name, 0) + 1
        elif name == "query_prometheus_metrics":
            if payload.get("status") == "success":
                successful_by_tool[name] = successful_by_tool.get(name, 0) + 1
        elif name == "query_prometheus_alerts":
            if payload.get("success") is True:
                successful_by_tool[name] = successful_by_tool.get(name, 0) + 1
        elif name in required:
            successful_by_tool[name] = successful_by_tool.get(name, 0) + 1

    missing = [name for name in required if name not in names or successful_by_tool.get(name, 0) == 0]
    evidence_errors: list[str] = []
    if "deployments" not in valid_namespaces:
        evidence_errors.append("没有成功读取 observability Deployment 数据")
    if "pods" not in valid_namespaces:
        evidence_errors.append("没有成功读取 observability Pod 数据")
    return {
        "required": required,
        "called": names,
        "missing": missing,
        "successful_tool_results": successful_by_tool,
        "valid_k8s_evidence": sorted(valid_namespaces),
        "evidence_errors": evidence_errors,
        "score": round(100 * (len(required) - len(missing)) / len(required), 2) if required else 100.0,
        "passed": not missing and not evidence_errors,
    }


def prompt_for_case(case: dict[str, Any]) -> str:
    expected_alerts = ", ".join(case.get("expected_alerts", [])) or "无（不要臆造告警）"
    expected_up = json.dumps(case.get("expected_up"), ensure_ascii=False)
    probe = case.get("expected_probe_success", "不适用")
    required = ", ".join(required_tools(case))
    return f"""
你正在诊断一个真实运行中的 K3s 集群，不是离线样例。当前场景标识：{case['scenario']}。
请只使用当前可用的只读 Kubernetes 与 Prometheus 工具取证，工具返回值是唯一事实来源；不要根据历史评测结果猜测。
必须先读取名称严格为 `observability`（拼写不是 observularity）的命名空间 Deployment/Pod 状态，再读取 Prometheus 告警；如果场景涉及 exporter/target 或资源异常，再用 PromQL 查询 up、probe_success、cAdvisor 或 node_filesystem 指标。
本场景必须成功调用这些工具并在报告中引用其返回值：{required}。如果第一次把 namespace 拼错，必须立即用 `observability` 重试；不能用空结果冒充证据。
不要调用任何重启、删除、扩缩容、systemd 或其他修改系统的工具；本次只做诊断和报告。
报告中请明确列出：服务/Pod 状态、Prometheus 告警（预期告警名仅供核对：{expected_alerts}）、关键指标证据、结论和不确定性。
评测元数据（不要直接当作事实，必须用工具验证）：expected_up={expected_up}，expected_probe_success={probe}。
""".strip()


async def run_case(service: Any, case: dict[str, Any], index: int, total: int) -> dict[str, Any]:
    started = time.perf_counter()
    print(f"[{index}/{total}] loading {case['scenario']}", flush=True)
    loaded = run_command(["bash", str(LOADER), case["scenario"]], timeout=300)
    result: dict[str, Any] = {
        "id": case["id"],
        "scenario": case["scenario"],
        "loader": {
            "returncode": loaded.returncode,
            "stdout": loaded.stdout[-8000:],
            "stderr": loaded.stderr[-4000:],
        },
        "environment": {
            "prometheus_base_url": os.environ["PROMETHEUS_BASE_URL"],
            "kubernetes_namespace": "observability",
            "tools_are_read_only": True,
        },
    }
    if loaded.returncode:
        result.update(
            {
                "error": "scenario loader failed",
                "trajectory": [],
                "tool_score": {"score": 0.0, "missing": required_tools(case)},
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        return result

    try:
        observation = await asyncio.to_thread(observe_case, case)
        result["cluster_observation"] = observation
        config = {"configurable": {"thread_id": f"k8s-live-{case['id']}-{index}"}}
        messages = [
            SystemMessage(content=service.system_prompt),
            HumanMessage(content=prompt_for_case(case)),
        ]
        agent_result = await service.agent.ainvoke({"messages": messages}, config=config)
        raw_messages = agent_result.get("messages", [])
        answer, calls = extract_trace(raw_messages)
        result["trajectory"] = [serialize_message(message) for message in raw_messages]
        result["tool_calls"] = calls
        result["answer"] = answer
        result["tool_score"] = tool_score(case, calls, result["trajectory"])
        # A read-only tool run must not alter the desired replica state.
        result["post_agent_deployments"] = await asyncio.to_thread(
            __import__("eval.run_k8s_scenario_eval", fromlist=["deployment_replicas"]).deployment_replicas
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result.setdefault("trajectory", [])
        result["tool_score"] = {"score": 0.0, "missing": required_tools(case)}
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    print(
        f"  cluster={result.get('cluster_observation', {}).get('score', 0):.2f}% "
        f"tools={result.get('tool_score', {}).get('score', 0):.2f}% "
        f"calls={len(result.get('tool_calls', []))}",
        flush=True,
    )
    return result


async def main(limit: int | None = None) -> int:
    import app.tools as runtime_tools
    import app.services.rag_agent_service as rag_service_module

    # rag_agent_service.py imports DEFAULT_LOCAL_AGENT_TOOLS by name and also
    # creates a production singleton at module import.  Patch both the module
    # binding and the instance used by this evaluator so no mutating/systemd
    # tool can accidentally enter the live K8s trajectory.
    runtime_tools.DEFAULT_LOCAL_AGENT_TOOLS = K8S_READ_ONLY_TOOLS
    rag_service_module.DEFAULT_LOCAL_AGENT_TOOLS = K8S_READ_ONLY_TOOLS
    service = rag_service_module.RagAgentService(streaming=False)
    service.tools = list(K8S_READ_ONLY_TOOLS)
    await service._initialize_agent()

    cases = load_cases()
    if limit is not None:
        cases = cases[:limit]
    results: list[dict[str, Any]] = []
    try:
        for index, case in enumerate(cases, start=1):
            results.append(await run_case(service, case, index, len(cases)))
    finally:
        restored = run_command(["bash", str(LOADER), "healthy"], timeout=300)
        if restored.returncode:
            print("WARNING: failed to restore healthy scenario", restored.stderr[-2000:], flush=True)

    cluster_scores = [item.get("cluster_observation", {}).get("score", 0.0) for item in results]
    tool_scores = [item.get("tool_score", {}).get("score", 0.0) for item in results]
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cases": len(results),
        "cluster_state_score": round(sum(cluster_scores) / len(cluster_scores), 2) if cluster_scores else 0.0,
        "agent_tool_score": round(sum(tool_scores) / len(tool_scores), 2) if tool_scores else 0.0,
        "agent_tool_pass_count": sum(1 for score in tool_scores if score == 100.0),
        "tool_mode": "live-k8s-prometheus-read-only",
        "prometheus_base_url": os.environ["PROMETHEUS_BASE_URL"],
        "results": results,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = RESULTS_DIR / f"k8s_agent_eval_{stamp}.json"
    md_path = RESULTS_DIR / f"k8s_agent_eval_{stamp}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Live K8s Agent Evaluation",
        "",
        f"- Cases: {len(results)}",
        f"- Cluster state score: {summary['cluster_state_score']:.2f}/100",
        f"- Agent live-tool score: {summary['agent_tool_score']:.2f}/100 ({summary['agent_tool_pass_count']}/{len(results)})",
        f"- Prometheus: `{summary['prometheus_base_url']}`",
        "- Tool mode: read-only Kubernetes API + local Prometheus HTTP API",
        "",
        "每个 case 的 JSON 中保存了完整 LangChain message trajectory，包括 AI tool_calls 和 ToolMessage 原始返回值。",
        "",
        "| Scenario | Cluster state | Agent tools | Calls | Error |",
        "|---|---:|---:|---:|---|",
    ]
    for item in results:
        error = str(item.get("error", "")).replace("|", "\\|")
        lines.append(
            f"| {item['scenario']} | {item.get('cluster_observation', {}).get('score', 0):.2f} "
            f"| {item.get('tool_score', {}).get('score', 0):.2f} "
            f"| {len(item.get('tool_calls', []))} | {error} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"JSON: {json_path}", flush=True)
    print(f"REPORT: {md_path}", flush=True)
    return 0 if summary["cluster_state_score"] == 100.0 and summary["agent_tool_score"] == 100.0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.limit)))
