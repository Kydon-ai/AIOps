#!/usr/bin/env python3
"""只读重算真实轨迹结果，避免修改原始运行记录。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.run_real_dataset_eval import load_dataset, score_case  # noqa: E402


def rescore(source: Path) -> tuple[dict, Path]:
    """用当前评分规则重算每条真实轨迹，并严格区分主指标与硬门槛。"""
    rows = {row["id"]: row for row in load_dataset()}
    result = json.loads(source.read_text(encoding="utf-8"))
    for item in result.get("cases", []):
        row = rows[item["id"]]
        item["validation"] = score_case(row, item.get("answer", ""), item.get("tool_calls", []), item.get("trajectory", []))

    selected = [rows[item["id"]] for item in result.get("cases", [])]
    by_id = {item["id"]: item for item in result.get("cases", [])}
    metric_rows = [row for row in selected if row["type"] != "hard_gate"]
    hard_rows = [row for row in selected if by_id[row["id"]]["validation"].get("hard_gate")]
    denominator = sum(float(row["target_weight_pct"]) for row in metric_rows)
    weighted = sum(float(row["target_weight_pct"]) * by_id[row["id"]]["validation"]["case_score"] for row in metric_rows)
    hard_items = [by_id[row["id"]] for row in hard_rows]
    result["summary"] = {
        "case_count": len(result.get("cases", [])),
        "metric_count": len(metric_rows),
        "weighted_score_pct": round(weighted / denominator * 100, 2) if denominator else 0.0,
        "hard_gate_count": len(hard_items),
        "hard_gate_passed": sum(bool(item["validation"].get("hard_gate_passed")) for item in hard_items),
        "all_hard_gates_passed": all(item["validation"].get("hard_gate_passed") for item in hard_items),
        "rescored_from": str(source),
    }
    target = source.with_name(f"{source.stem}_rescored_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result, target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    result, target = rescore(args.source)
    print(f"JSON: {target}")
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0 if result["summary"]["weighted_score_pct"] >= 80 and result["summary"]["all_hard_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
