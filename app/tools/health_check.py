"""Read-only HTTP health check for services in the managed allowlist."""

from __future__ import annotations

import json
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from langchain_core.tools import tool

from app.config import config


@tool
def health_check(service_name: str) -> str:
    """请求受控服务的健康端点并返回 HTTP 状态、响应体和错误信息。"""
    name = service_name.strip()
    url = config.managed_http_service_urls.get(name)
    if not url:
        return json.dumps(
            {"success": False, "service": name, "error": "服务没有配置健康检查地址", "allowed_services": sorted(config.managed_http_service_urls)},
            ensure_ascii=False,
        )
    last_error = ""
    for attempt in range(5):
        try:
            request = Request(url, headers={"Accept": "application/json"})
            with urlopen(request, timeout=config.service_log_timeout) as response:
                body = response.read(4096).decode("utf-8", errors="replace")
                return json.dumps({"success": True, "service": name, "url": url, "status": response.status, "body": body, "attempt": attempt + 1}, ensure_ascii=False)
        except (URLError, OSError) as exc:
            last_error = str(exc)
            if attempt < 4:
                time.sleep(0.5)
    return json.dumps({"success": False, "service": name, "url": url, "status": None, "error": last_error}, ensure_ascii=False)
