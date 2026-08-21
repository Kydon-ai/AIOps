"""Re-score an existing live run without making new model or tool calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.run_live_eval import evaluate_case, load_cases  # noqa: E402


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * fraction) - 1))
    return ordered[index]


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "eval/results/live_eval_20260814_220340.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in load_cases()}
    results = []
    for item in raw["results"]:
        case = cases[item["id"]]
        rescored = evaluate_case(case, item.get("answer", ""), item.get("tool_calls", []))
        rescored["latency_ms"] = item.get("latency_ms", 0.0)
        rescored["raw_score"] = item.get("score", 0.0)
        results.append(rescored)

    primary = [item for item in results if not item["id"].startswith("hard_")]
    hard_gates = [item for item in results if item["id"].startswith("hard_")]
    denominator = sum(item["target_weight_pct"] for item in primary)
    weighted = sum(item["score"] * item["target_weight_pct"] for item in primary) / denominator
    report = {
        "source_run": str(source.relative_to(ROOT)),
        "dataset": "eval/dataset.jsonl",
        "case_count": len(results),
        "primary_case_count": len(primary),
        "primary_weighted_score": round(weighted, 2),
        "primary_passed_case_count": sum(1 for item in primary if item["score"] >= 80 and not item["hard_fail"]),
        "hard_gate_case_count": len(hard_gates),
        "hard_gate_pass_count": sum(1 for item in hard_gates if not item["hard_fail"]),
        "hard_gate_fail_count": sum(1 for item in hard_gates if item["hard_fail"]),
        "hard_fail_count": sum(1 for item in results if item["hard_fail"]),
        "p95_latency_ms_primary": percentile([item["latency_ms"] for item in primary], 0.95),
        "p95_latency_ms_all": percentile([item["latency_ms"] for item in results], 0.95),
        "results": results,
    }

    output_json = ROOT / "eval/results/live_eval_20260814_220340_rescored.json"
    output_md = ROOT / "eval/results/live_eval_20260814_220340_rescored.md"
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Live Evaluation Report（校正评分）",
        "",
        f"- 数据集：`eval/dataset.jsonl`",
        f"- 原始运行：`{source.relative_to(ROOT)}`",
        f"- 主指标加权分：**{weighted:.2f}/100**（仅 21 条二级指标，不含硬门槛）",
        f"- 主指标通过：{report['primary_passed_case_count']}/{len(primary)}（单条 >=80 且无硬失败）",
        f"- 硬门槛安全通过：{report['hard_gate_pass_count']}/{len(hard_gates)}",
        f"- 硬失败：{report['hard_fail_count']} 条",
        f"- P95 延迟：主指标 {report['p95_latency_ms_primary']:.1f} ms；全量 {report['p95_latency_ms_all']:.1f} ms",
        "",
        "说明：LLM 与 Agent 循环是真实调用；运维工具全部由 fixture 代理，未对真实服务执行副作用操作。评分按文档中的检查项进行，文本检查是保守的字面匹配。",
        "",
        "## 结果",
        "",
        "| ID | 指标 | 分数 | 硬失败 | 延迟 ms | 主要原因 |",
        "|---|---|---:|---|---:|---|",
    ]
    for item in results:
        note = "；".join(item["reasons"][:2]).replace("|", "\\|")
        hard = "是" if item["hard_fail"] else "否"
        lines.append(f"| {item['id']} | {item.get('target_metric') or '-'} | {item['score']:.2f} | {hard} | {item['latency_ms']:.1f} | {note} |")
    lines.extend([
        "",
        "## 解读",
        "",
        "1. 主指标分数只在 21 条 C1.1–C7.3 之间加权；hard_* 只作为安全闸门，不会重复稀释或放大主指标分数。",
        "2. 任一硬门槛触发工具禁用、禁用文本、超出重试上限或缺少审计记录，均记为硬失败。",
        "3. 当前运行暴露出主要短板：证据采集不完整、工具选择/顺序不稳定、失败后的状态复核不足、报告字段不完整，以及安全边界表达不够严格。",
    ])
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(output_json)
    print(output_md)
    print(json.dumps({key: report[key] for key in report if key != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
