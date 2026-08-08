"""工具模块 - 供 Agent 调用的各种工具"""

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
from app.tools.save_warning_log import save_warning_log
from app.tools.top_cpu_processes import get_top_cpu_processes
from app.tools.time_tool import get_current_time

# 默认本地工具集：凡绑定「知识库 + 时间」的 Agent 应使用此元组，与 Prometheus 告警查询一并注册
DEFAULT_LOCAL_AGENT_TOOLS = (
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
    save_warning_log,
    get_top_cpu_processes,
)

__all__ = [
    "DEFAULT_LOCAL_AGENT_TOOLS",
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
    "save_warning_log",
    "get_top_cpu_processes",
]
