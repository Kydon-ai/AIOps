"""合并同一批真实评测的重跑结果，保留每个题目最新的完整轨迹。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def merge_results(base_path: str, replacement_paths: list[str]) -> dict[str, Any]:
    """按题目 ID 合并真实结果，不生成或替换任何工具调用。"""
    base = json.loads(Path(base_path).read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in base.get("cases", [])}
    sources: dict[str, str] = {item["id"]: base_path for item in base.get("cases", [])}
    for path in replacement_paths:
        result = json.loads(Path(path).read_text(encoding="utf-8"))
        for item in result.get("cases", []):
            by_id[item["id"]] = item
            sources[item["id"]] = path
    merged = dict(base)
    merged["cases"] = list(by_id.values())
    merged["merged_from"] = sources
    merged["merged_at"] = datetime.now().isoformat(timespec="seconds")
    return merged


def main() -> int:
    """解析参数并写出合并后的真实轨迹文件。"""
    parser = argparse.ArgumentParser(description="合并真实评测重跑结果")
    parser.add_argument("base")
    parser.add_argument("replacements", nargs="+")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = merge_results(args.base, args.replacements)
    output = Path(args.output) if args.output else Path(args.base).with_name(f"{Path(args.base).stem}_merged.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
