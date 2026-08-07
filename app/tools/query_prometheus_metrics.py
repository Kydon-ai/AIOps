"""PromQL 查询工具。"""

import json

import httpx
from langchain_core.tools import tool
from loguru import logger

from app.config import config


@tool
def query_prometheus_metrics(query: str) -> str:
    """使用 PromQL 查询当前服务器指标。

    这是只读工具，适合查询 CPU、内存、磁盘、网络、targets 和应用健康状态。
    示例：
    - up
    - node_load1{job="node"}
    - 100 * (1 - avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m])))
    """
    expression = query.strip()
    if not expression:
        return json.dumps({"success": False, "error": "PromQL 不能为空"}, ensure_ascii=False)

    base_url = config.prometheus_base_url.rstrip("/")
    url = f"{base_url}/api/v1/query"
    try:
        with httpx.Client(timeout=config.prometheus_request_timeout) as client:
            response = client.get(url, params={"query": expression})
            response.raise_for_status()
            body = response.json()
        logger.info("PromQL 查询完成: {}", expression)
        return json.dumps(body, ensure_ascii=False)
    except Exception as exc:
        logger.error("PromQL 查询失败: {}", exc)
        return json.dumps(
            {"success": False, "error": str(exc), "query": expression},
            ensure_ascii=False,
        )

