"""Node Exporter/Blackbox Exporter 的受控 Docker MCP 服务。

默认监听 127.0.0.1:8007/mcp。Docker 不存在时返回结构化错误，
不会把 K3s/containerd 中的 Pod 冒充成 Docker 容器。
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from app.tools.docker_resources import (
    get_docker_containers as local_get_docker_containers,
    restart_docker_container as local_restart_docker_container,
)


mcp = FastMCP(
    "docker-exporter-recovery",
    instructions=(
        "提供 Node Exporter 和 Blackbox Exporter 的受控 Docker 检查/重启能力。"
        "工具内部固定执行 docker ps -a；只有唯一匹配且已停止的受控容器才允许重启。"
        "Docker 不可用、容器不存在或匹配不唯一时必须如实报告，不得改用任意 Shell。"
    ),
    host=os.getenv("DOCKER_MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("DOCKER_MCP_PORT", "8007")),
    streamable_http_path="/mcp",
)


@mcp.tool()
def get_docker_containers(service_name: str = "") -> str:
    """执行固定的 docker ps -a，查找受控 exporter 容器。"""
    return local_get_docker_containers.invoke({"service_name": service_name})


@mcp.tool()
def restart_docker_container(service_name: str) -> str:
    """重启唯一匹配的已停止 exporter 容器，并返回真实复核结果。"""
    return local_restart_docker_container.invoke({"service_name": service_name})


if __name__ == "__main__":
    mcp.run(transport=os.getenv("DOCKER_MCP_TRANSPORT", "streamable-http"))
