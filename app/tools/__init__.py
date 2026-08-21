"""工具模块 - 供 Agent 调用的各种工具"""

from app.config import config
from app.tools.knowledge_tool import retrieve_knowledge
from app.tools.disk_usage import get_directory_disk_usage, get_disk_filesystems
from app.tools.query_metrics_alerts import query_prometheus_alerts
from app.tools.query_prometheus_metrics import query_prometheus_metrics
from app.tools.process_details import get_process_details
from app.tools.check_systemd_service import check_systemd_service
from app.tools.list_skills import list_skills
from app.tools.read_service_logs import read_service_logs
from app.tools.read_skill import read_skill
from app.tools.restart_systemd_service import restart_systemd_service
from app.tools.stop_systemd_service import stop_systemd_service
from app.tools.save_warning_log import save_warning_log
from app.tools.top_cpu_processes import get_top_cpu_processes
from app.tools.time_tool import get_current_time
from app.tools.health_check import health_check
from app.tools.memory_diagnostics import get_memory_summary, get_top_memory_processes, get_oom_events
from app.tools.kubernetes_resources import (
    get_kubernetes_deployments,
    get_kubernetes_events,
    get_kubernetes_nodes,
    get_kubernetes_pod_logs,
    get_kubernetes_pods,
)
from app.tools.docker_resources import get_docker_containers, restart_docker_container

# 默认本地工具集：凡绑定「知识库 + 时间」的 Agent 应使用此元组，与 Prometheus 告警查询一并注册
BASE_LOCAL_AGENT_TOOLS = (
    retrieve_knowledge,
    get_current_time,
    query_prometheus_alerts,
    query_prometheus_metrics,
    get_disk_filesystems,
    get_directory_disk_usage,
    get_process_details,
    check_systemd_service,
    list_skills,
    read_skill,
    read_service_logs,
    restart_systemd_service,
    stop_systemd_service,
    save_warning_log,
    get_top_cpu_processes,
    health_check,
    get_memory_summary,
    get_top_memory_processes,
    get_oom_events,
    get_docker_containers,
    restart_docker_container,
)

# In production, systemd mutations are provided by the formal systemd MCP.
# Keeping the local copies out avoids duplicate tool names and prevents the
# Agent from silently bypassing the MCP process' execution identity.
PRODUCTION_LOCAL_AGENT_TOOLS = tuple(
    tool
    for tool in BASE_LOCAL_AGENT_TOOLS
    if getattr(tool, "name", "") not in {
        "check_systemd_service",
        "restart_systemd_service",
        "stop_systemd_service",
    }
)

# Local Kubernetes tools are only for local K8s evaluation/development.
# Production Kubernetes access must come from the formal MCP.
LOCAL_K8S_AGENT_TOOLS = (
    get_kubernetes_deployments,
    get_kubernetes_pods,
    get_kubernetes_events,
    get_kubernetes_pod_logs,
    get_kubernetes_nodes,
)


def build_local_agent_tools() -> tuple:
    """Build the local registry for the selected runtime environment."""
    if config.env_flag == "production":
        return PRODUCTION_LOCAL_AGENT_TOOLS
    return BASE_LOCAL_AGENT_TOOLS + LOCAL_K8S_AGENT_TOOLS


# Resolve once during application startup so a runtime env change cannot
# silently change the Agent's tool permissions.
DEFAULT_LOCAL_AGENT_TOOLS = build_local_agent_tools()

__all__ = [
    "DEFAULT_LOCAL_AGENT_TOOLS",
    "BASE_LOCAL_AGENT_TOOLS",
    "PRODUCTION_LOCAL_AGENT_TOOLS",
    "LOCAL_K8S_AGENT_TOOLS",
    "build_local_agent_tools",
    "retrieve_knowledge",
    "get_current_time",
    "query_prometheus_alerts",
    "query_prometheus_metrics",
    "get_disk_filesystems",
    "get_directory_disk_usage",
    "get_process_details",
    "check_systemd_service",
    "list_skills",
    "read_skill",
    "read_service_logs",
    "restart_systemd_service",
    "stop_systemd_service",
    "save_warning_log",
    "get_top_cpu_processes",
    "health_check",
    "get_memory_summary",
    "get_top_memory_processes",
    "get_oom_events",
    "get_kubernetes_deployments",
    "get_kubernetes_pods",
    "get_kubernetes_events",
    "get_kubernetes_pod_logs",
    "get_kubernetes_nodes",
    "get_docker_containers",
    "restart_docker_container",
]
