"""统一加载真实评测场景，不替换 Agent 工具或工具注册表。"""

from __future__ import annotations

import json
import os
import subprocess
import time
from urllib.request import urlopen
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "eval" / "scenario_catalog.json"
K8S_LOADER = ROOT / "k8s" / "load-scenario.sh"
UBUNTU_CONTROL = ROOT / "k8s" / "real-env" / "real-eval-control.sh"
POLICY_PATH = ROOT / "data" / "eval_runtime" / "service_policy.json"


def catalog() -> dict[str, Any]:
    """读取场景目录并返回结构化配置。"""
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _run(command: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    """以非 shell 参数执行场景控制脚本，保留 stdout/stderr 供审计。"""
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)


def _set_policy(policy: str | None) -> None:
    """写入正式工具读取的测试服务策略；健康场景删除临时策略。"""
    if policy == "deny-dblog":
        POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
        POLICY_PATH.write_text(json.dumps({"managed_http_services": {"rag": "rag.service"}, "managed_http_service_urls": {}}, ensure_ascii=False), encoding="utf-8")
        os.environ["SERVICE_POLICY_FILE"] = str(POLICY_PATH)
    else:
        POLICY_PATH.unlink(missing_ok=True)
        os.environ.pop("SERVICE_POLICY_FILE", None)


def load_scenario(scenario_id: str) -> dict[str, Any]:
    """按 scenario_id 切换真实 K8s/Ubuntu 状态并返回控制日志。"""
    item = catalog().get("scenarios", {}).get(scenario_id)
    if not item:
        raise KeyError(f"unknown scenario_id: {scenario_id}")
    _set_policy(item.get("policy"))
    if item["loader"] == "k8s":
        result = _run(["bash", str(K8S_LOADER), item["name"]])
    elif item["loader"] == "ubuntu":
        result = _run(["bash", str(UBUNTU_CONTROL), item["name"]], timeout=60)
    else:
        raise ValueError(f"unsupported loader: {item['loader']}")
    if result.returncode != 0:
        raise RuntimeError(f"scenario load failed: {scenario_id}: {result.stderr[-2000:]}")
    if item["loader"] == "ubuntu" and item["name"] == "failed":
        # systemd 刚完成 restart 时可能短暂显示 active；等待真实 failed
        # 状态后再把控制权交给 Agent，避免把启动竞态当成诊断结果。
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            probe = _run(["systemctl", "--user", "is-failed", "dblog-backend.service"], timeout=10)
            if probe.returncode == 0:
                break
            time.sleep(1)
    # Prometheus Pod ready 并不等于已经完成一次 scrape；资源和目标故障的
    # 评测必须给 exporter 一个真实预热窗口，避免把空结果当成正常状态。
    warmup = max(0, int(item.get("warmup_seconds", 0)))
    deadline = time.monotonic() + warmup
    ready = False
    while time.monotonic() < deadline:
        try:
            with urlopen("http://127.0.0.1:9090/-/ready", timeout=2) as response:
                if response.status == 200:
                    ready = True
                    break
        except OSError:
            pass
        time.sleep(1)
    # 即使 Prometheus 很快 ready，也要等到场景声明的完整窗口，让
    # scrape 和 alert ``for`` 持续时间真正满足，而不是读到空结果。
    while time.monotonic() < deadline:
        time.sleep(min(1, max(0.1, deadline - time.monotonic())))
    return {"scenario_id": scenario_id, "config": item, "stdout": result.stdout[-4000:], "stderr": result.stderr[-2000:]}


def restore_baseline() -> None:
    """把真实环境恢复到可复用的健康基线。"""
    _set_policy(None)
    k8s = _run(["bash", str(K8S_LOADER), "healthy"])
    ubuntu = _run(["bash", str(UBUNTU_CONTROL), "healthy-start"], timeout=60)
    if k8s.returncode != 0 or ubuntu.returncode != 0:
        raise RuntimeError("failed to restore healthy baseline")
