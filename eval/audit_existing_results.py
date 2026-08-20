"""只读审计已保存真实评测结果，帮助区分评分规则过严与 Agent 真实缺陷。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.run_real_dataset_eval import load_dataset, score_case


def main() -> None:
    rows = {row["id"]: row for row in load_dataset()}
    for path in sorted((Path(__file__).parent / "results").glob("real_dataset_eval_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data.get("cases", []):
            row = rows.get(item.get("id"))
            if not row:
                continue
            validation = score_case(row, item.get("answer", ""), item.get("tool_calls", []), item.get("trajectory", []))
            failed = [check["name"] for check in validation["checks"] if not check["passed"]]
            print(path.name, item["id"], validation["case_score"], failed)


if __name__ == "__main__":
    main()
