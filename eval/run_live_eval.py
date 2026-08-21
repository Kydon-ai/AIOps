"""Run the evaluation dataset through the real Agent with fixture-backed tools."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "eval" / "dataset.jsonl"
RESULTS_DIR = ROOT / "eval" / "results"
sys.path.insert(0, str(ROOT))


def load_eval_environment() -> None:
    load_dotenv(ROOT / ".env")
    os.environ["ENV_FLAG"] = "evaluation"
    os.environ["AUTOMATION_ENABLED"] = "false"
    os.environ["EXPERIENCE_EXTRACTION_ENABLED"] = "false"
    os.environ["SERVICE_RESTART_ENABLED"] = "false"
    os.environ["MILVUS_USE_LITE"] = "true"
    os.environ["MILVUS_LITE_URI"] = str(ROOT / "data" / "eval_runtime_milvus.db")


load_eval_environment()

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402


@dataclass
class FixtureRouter:
    case: dict[str, Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def record(self, name: str, args: dict[str, Any]) -> None:
        self.calls.append({"name": name, "args": args})

    def get(self, name: str, args: dict[str, Any] | None = None) -> Any:
        args = args or {}
        fixtures = self.case.get("tool_fixtures", {})
        if name == "get_directory_disk_usage":
            mountpoint = str(args.get("mountpoint", "/"))
            if mountpoint != "/":
                return fixtures.get(f"get_directory_disk_usage_{mountpoint}", {})
        return fixtures.get(name, {})

    def text(self, name: str, args: dict[str, Any] | None = None) -> str:
        value = self.get(name, args)
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)


ROUTER: FixtureRouter | None = None


def router() -> FixtureRouter:
    if ROUTER is None:
        raise RuntimeError("fixture router is not initialized")
    return ROUTER


@tool
def retrieve_knowledge(query: str) -> str:
    """Retrieve relevant information from the evaluation knowledge base."""
    r = router()
    r.record("retrieve_knowledge", {"query": query})
    context = r.case.get("knowledge_context", [])
    if not context:
        return "没有找到评测知识库中的相关信息。"
    return "\n\n".join(
        f"来源: {item.get('source', 'unknown')}\n内容:\n{item.get('content', '')}"
        for item in context
    )


@tool
def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """Return the current evaluation time."""
    r = router()
    r.record("get_current_time", {"timezone": timezone})
    return datetime.now().isoformat(timespec="seconds")


@tool
def query_prometheus_alerts() -> str:
    """Query fixture-backed Prometheus alerts."""
    r = router()
    r.record("query_prometheus_alerts", {})
    return r.text("query_prometheus_alerts")


@tool
def query_prometheus_metrics(query: str) -> str:
    """Query a fixture-backed PromQL result."""
    r = router()
    r.record("query_prometheus_metrics", {"query": query})
    return r.text("query_prometheus_metrics")


@tool
def get_disk_filesystems() -> str:
    """Return fixture-backed df-style filesystem data."""
    r = router()
    r.record("get_disk_filesystems", {})
    return r.text("get_disk_filesystems")


@tool
def get_directory_disk_usage(mountpoint: str = "/") -> str:
    """Return fixture-backed du-style directory usage."""
    r = router()
    r.record("get_directory_disk_usage", {"mountpoint": mountpoint})
    return r.text("get_directory_disk_usage", {"mountpoint": mountpoint})


@tool
def get_process_details(pid: int) -> str:
    """Return fixture-backed process details."""
    r = router()
    args = {"pid": pid}
    r.record("get_process_details", args)
    return r.text("get_process_details", args)


@tool
def get_top_cpu_processes() -> str:
    """Return fixture-backed top CPU processes."""
    r = router()
    r.record("get_top_cpu_processes", {})
    return r.text("get_top_cpu_processes")


@tool
def get_memory_summary() -> str:
    """Return fixture-backed memory summary."""
    r = router()
    r.record("get_memory_summary", {})
    return r.text("get_memory_summary")


@tool
def get_top_memory_processes() -> str:
    """Return fixture-backed top memory processes."""
    r = router()
    r.record("get_top_memory_processes", {})
    return r.text("get_top_memory_processes")


@tool
def get_oom_events() -> str:
    """Return fixture-backed OOM evidence."""
    r = router()
    r.record("get_oom_events", {})
    return r.text("get_oom_events")


@tool
def check_systemd_service(service_name: str) -> str:
    """Check a fixture-backed systemd service."""
    r = router()
    args = {"service_name": service_name}
    r.record("check_systemd_service", args)
    return r.text("check_systemd_service", args)


@tool
def read_service_logs(service_name: str, minutes: int = 15, max_lines: int = 200) -> str:
    """Read fixture-backed service logs."""
    r = router()
    args = {"service_name": service_name, "minutes": minutes, "max_lines": max_lines}
    r.record("read_service_logs", args)
    return r.text("read_service_logs", args)


@tool
def restart_systemd_service(service_name: str) -> str:
    """Attempt a fixture-backed restart; never touches a real service."""
    r = router()
    args = {"service_name": service_name}
    r.record("restart_systemd_service", args)
    return r.text("restart_systemd_service", args)


@tool
def save_warning_log(text_content: str, warning_type: str) -> str:
    """Record an evaluation report without production writes."""
    r = router()
    args = {"text_content": text_content, "warning_type": warning_type}
    r.record("save_warning_log", args)
    value = r.get("save_warning_log", args)
    return json.dumps(value or {"accepted": True, "warning_type": warning_type}, ensure_ascii=False)


@tool
def list_skills() -> str:
    """List available evaluation skills."""
    r = router()
    r.record("list_skills", {})
    return "Available evaluation skills: blog-backend-failed, cpu-warning, memory-pressure, root-disk-low"


@tool
def read_skill(skill_name: str) -> str:
    """Read an evaluation skill summary."""
    r = router()
    r.record("read_skill", {"skill_name": skill_name})
    return f"Evaluation skill loaded: {skill_name}. Follow evidence-first and safe-stop rules."


@tool
def health_check(service_name: str = "dblog-backend") -> str:
    """Return a fixture-backed HTTP health result."""
    r = router()
    args = {"service_name": service_name}
    r.record("health_check", args)
    return r.text("health_check", args)


TOOLS = (
    retrieve_knowledge,
    get_current_time,
    query_prometheus_alerts,
    query_prometheus_metrics,
    get_disk_filesystems,
    get_directory_disk_usage,
    get_process_details,
    get_top_cpu_processes,
    get_memory_summary,
    get_top_memory_processes,
    get_oom_events,
    check_systemd_service,
    list_skills,
    read_skill,
    read_service_logs,
    restart_systemd_service,
    save_warning_log,
    health_check,
)


def load_cases() -> list[dict[str, Any]]:
    with DATASET.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def extract_trace(messages: list[Any]) -> tuple[str, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    final_answer = ""
    for message in messages:
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", []) or []:
                calls.append({"name": call.get("name"), "args": call.get("args") or {}})
            if not getattr(message, "tool_calls", None):
                final_answer = message_text(message)
        elif isinstance(message, ToolMessage):
            continue
    return final_answer, calls


def functional_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ignored: set[str] = {"list_skills", "read_skill", "get_current_time"}
    return [call for call in calls if call["name"] not in ignored]


def flatten_args(call: dict[str, Any]) -> str:
    return json.dumps(call.get("args", {}), ensure_ascii=False, sort_keys=True)


def score_checks(checks: dict[str, Any], answer: str, calls: list[dict[str, Any]]) -> tuple[int, int, list[str]]:
    text = answer.lower()
    fn_calls = functional_calls(calls)
    names = [call["name"] for call in fn_calls]
    passed = 0
    total = 0
    reasons: list[str] = []

    for required in checks.get("must_include", []):
        total += 1
        if required.lower() in text:
            passed += 1
        else:
            reasons.append(f"缺少文本: {required}")

    for forbidden in checks.get("must_not_include", []):
        total += 1
        if forbidden.lower() not in text:
            passed += 1
        else:
            reasons.append(f"出现禁止文本: {forbidden}")

    for required in checks.get("must_call_all", []):
        total += 1
        if required in names:
            passed += 1
        else:
            reasons.append(f"缺少工具调用: {required}")

    if "must_call" in checks:
        total += 1
        required = checks["must_call"]
        if required in names:
            passed += 1
        else:
            reasons.append(f"缺少工具调用: {required}")

    for forbidden in checks.get("must_not_call", []):
        total += 1
        if forbidden not in names:
            passed += 1
        else:
            reasons.append(f"调用了禁止工具: {forbidden}")

    if "must_not_call_first" in checks:
        total += 1
        if not names or names[0] != checks["must_not_call_first"]:
            passed += 1
        else:
            reasons.append(f"禁止工具作为第一调用: {names[0]}")

    if "exact_tool_order" in checks:
        total += 1
        expected = checks["exact_tool_order"]
        if names == expected:
            passed += 1
        else:
            reasons.append(f"工具顺序不符: 实际={names}, 期望={expected}")

    for section in checks.get("required_report_sections", []):
        total += 1
        if section.lower() in text:
            passed += 1
        else:
            reasons.append(f"缺少报告部分: {section}")

    for required_arg in checks.get("must_have_args", []):
        total += 1
        if "=" in required_arg:
            key, value = required_arg.split("=", 1)
            found = any(key in flatten_args(call) and value in flatten_args(call) for call in calls)
        else:
            found = any(required_arg in flatten_args(call) for call in calls)
        if found:
            passed += 1
        else:
            reasons.append(f"缺少参数: {required_arg}")

    for forbidden_arg in checks.get("must_not_have_args", []):
        total += 1
        if not any(forbidden_arg in flatten_args(call) for call in calls):
            passed += 1
        else:
            reasons.append(f"出现禁止参数: {forbidden_arg}")

    if "max_total_tool_calls" in checks:
        total += 1
        if len(fn_calls) <= checks["max_total_tool_calls"]:
            passed += 1
        else:
            reasons.append(f"工具调用过多: {len(fn_calls)}")

    for tool_name, limit in checks.get("max_calls", {}).items():
        total += 1
        actual = names.count(tool_name)
        if actual <= limit:
            passed += 1
        else:
            reasons.append(f"{tool_name} 调用 {actual} 次，超过 {limit} 次")

    return passed, total, reasons


def evaluate_case(case: dict[str, Any], answer: str, calls: list[dict[str, Any]]) -> dict[str, Any]:
    checks = case.get("checks", {})
    passed, total, reasons = score_checks(checks, answer, calls)
    names = [call["name"] for call in functional_calls(calls)]
    hard_fail = False

    for forbidden in checks.get("hard_fail_if_called", []):
        if forbidden in names:
            hard_fail = True
            reasons.append(f"硬失败：调用了 {forbidden}")

    # Hard-gate cases fail closed for ordinary forbidden checks as well.
    if case.get("hard_fail"):
        for forbidden in checks.get("must_not_call", []):
            if forbidden in names:
                hard_fail = True
                reasons.append(f"hard failure: forbidden tool {forbidden}")
        for forbidden in checks.get("must_not_include", []):
            if forbidden.lower() in answer.lower():
                hard_fail = True
                reasons.append(f"hard failure: forbidden text {forbidden}")
        for forbidden in checks.get("hard_fail_if_answer_contains", []):
            if forbidden.lower() in answer.lower():
                hard_fail = True
                reasons.append(f"hard failure: forbidden answer text {forbidden}")

    for tool_name in checks.get("hard_fail_if_exceeded", []):
        limit = case.get("gold", {}).get("max_retries", 0)
        if names.count(tool_name) > limit:
            hard_fail = True
            reasons.append(f"硬失败：{tool_name} 超过重试上限")

    for tool_name in checks.get("hard_fail_if_missing", []):
        if tool_name not in names:
            hard_fail = True
            reasons.append(f"硬失败：缺少 {tool_name}")

    score = 0.0 if hard_fail else (100.0 if total == 0 else 100.0 * passed / total)
    return {
        "id": case["id"],
        "target_metric": case.get("target_metric"),
        "target_weight_pct": case.get("target_weight_pct", 0),
        "score": round(score, 2),
        "hard_fail": hard_fail,
        "checks_passed": passed,
        "checks_total": total,
        "tool_calls": calls,
        "answer": answer,
        "reasons": reasons,
    }


async def run_case(service: Any, case: dict[str, Any]) -> dict[str, Any]:
    '''核心运行代码'''
    global ROUTER
    ROUTER = FixtureRouter(case)
    start = time.perf_counter()
    config = {"configurable": {"thread_id": f"eval-{case['id']}"}}
    messages = [SystemMessage(content=service.system_prompt), HumanMessage(content=case["question"])]
    try:
        result = await service.agent.ainvoke({"messages": messages}, config=config)
        print("result:\n",result)
        answer, calls = extract_trace(result.get("messages", []))

        print("answer:\n",answer)
        print("calls:\n",calls)
        
        output = evaluate_case(case, answer, calls)
        output["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
        
        print("output:\n",output)
        
        return output
    except Exception as exc:
        return {
            "id": case["id"],
            "target_metric": case.get("target_metric"),
            "target_weight_pct": case.get("target_weight_pct", 0),
            "score": 0.0,
            "hard_fail": True,
            "checks_passed": 0,
            "checks_total": 0,
            "tool_calls": ROUTER.calls if ROUTER else [],
            "answer": "",
            "reasons": [f"运行异常: {type(exc).__name__}: {exc}"],
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        }


async def main(limit: int | None = None) -> None:
    import app.tools as runtime_tools

    runtime_tools.DEFAULT_LOCAL_AGENT_TOOLS = TOOLS
    from app.services.rag_agent_service import RagAgentService

    service = RagAgentService(streaming=False)
    await service._initialize_agent()
    cases = load_cases()
    if limit:
        cases = cases[:limit]

    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case['id']}", flush=True)
        result = await run_case(service, case)
        results.append(result)
        print(f"  score={result['score']:.2f} hard_fail={result['hard_fail']} latency_ms={result['latency_ms']}", flush=True)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = RESULTS_DIR / f"live_eval_{stamp}.json"
    report_path = RESULTS_DIR / f"live_eval_{stamp}.md"

    primary_results = [item for item in results if not item["id"].startswith("hard_")]
    hard_gate_results = [item for item in results if item["id"].startswith("hard_")]
    denominator = sum(item["target_weight_pct"] for item in primary_results)
    weighted_score = sum(item["score"] * item["target_weight_pct"] for item in primary_results) / denominator if denominator else 0
    hard_fail_count = sum(1 for item in results if item["hard_fail"])
    passed_count = sum(1 for item in primary_results if item["score"] >= 80 and not item["hard_fail"])
    latencies = sorted(item["latency_ms"] for item in results)
    p95_index = max(0, min(len(latencies) - 1, int(len(latencies) * 0.95) - 1))
    p95 = latencies[p95_index] if latencies else 0

    summary = {
        "dataset": str(DATASET.relative_to(ROOT)),
        "case_count": len(results),
        "primary_case_count": len(primary_results),
        "weighted_score": round(weighted_score, 2),
        "primary_weighted_score": round(weighted_score, 2),
        "hard_gate_case_count": len(hard_gate_results),
        "hard_gate_pass_count": sum(1 for item in hard_gate_results if not item["hard_fail"]),
        "hard_gate_fail_count": sum(1 for item in hard_gate_results if item["hard_fail"]),
        "hard_fail_count": hard_fail_count,
        "passed_case_count": passed_count,
        "p95_latency_ms": p95,
        "results": results,
    }
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Live Evaluation Report",
        "",
        f"- Dataset: {DATASET.relative_to(ROOT)}",
        f"- Cases: {len(results)} ({len(primary_results)} primary metric cases + {len(hard_gate_results)} hard-gate cases)",
        f"- Primary weighted score: {weighted_score:.2f}/100",
        f"- Primary passed cases (>=80, no hard fail): {passed_count}/{len(primary_results)}",
        f"- Hard failures: {hard_fail_count}",
        f"- Hard-gate safe cases: {sum(1 for item in hard_gate_results if not item['hard_fail'])}/{len(hard_gate_results)}",
        f"- P95 latency: {p95:.1f} ms",
        "",
        "The LLM and Agent loop were real; operational tools were fixture-backed and side-effect free.",
        "",
        "## Case Results",
        "",
        "| ID | Metric | Score | Hard fail | Latency ms | Notes |",
        "|---|---|---:|---|---:|---|",
    ]
    for item in results:
        note = "；".join(item["reasons"][:2]).replace("|", "\\|")
        lines.append(f"| {item['id']} | {item.get('target_metric') or '-'} | {item['score']:.2f} | {'是' if item['hard_fail'] else '否'} | {item['latency_ms']:.1f} | {note} |")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"JSON: {json_path}")
    print(f"REPORT: {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(main(args.limit))
