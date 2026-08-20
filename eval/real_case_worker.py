#!/usr/bin/env python3
"""在独立进程中运行单条真实评测，便于父进程实施硬超时。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.run_real_dataset_eval import RagAgentService, ask, evaluation_question  # noqa: E402


async def run(row: dict, session_id: str) -> dict:
    """只使用生产 Agent 和生产工具完成一条调用，不加载任何 fixture。"""
    service = RagAgentService(streaming=False)
    await service._initialize_agent()
    return await ask(service, evaluation_question(row), session_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--row", required=True, help="单条 JSON 记录路径")
    parser.add_argument("--output", required=True, help="结果 JSON 输出路径")
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()

    row = json.loads(Path(args.row).read_text(encoding="utf-8"))
    output = Path(args.output)
    try:
        item = asyncio.run(run(row, args.session_id))
    except Exception as exc:  # pragma: no cover - 由父进程记录真实失败
        item = {
            "answer": "",
            "tool_calls": [],
            "trajectory": [],
            "latency_ms": None,
            "error": f"worker failed: {exc}",
            "traceback": traceback.format_exc(limit=12),
        }
        output.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    output.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
