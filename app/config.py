"""配置管理模块

使用 Pydantic Settings 实现类型安全的配置管理
"""

import os
from typing import  Any
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用配置
    app_name: str = "SuperBizAgent"
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 9900

    # DashScope 配置
    dashscope_api_key: str = os.getenv('DASHSCOPE_API_KEY',"")  # 默认空字符串，实际使用需从环境变量加载
    dashscope_api_base:str = os.getenv('DASHSCOPE_API_BASE',"")
    dashscope_model: str = "qwen-max"
    dashscope_embedding_model: str = "text-embedding-v4"  # v4 支持多种维度（默认 1024）

    # Milvus 配置
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_timeout: int = 10000  # 毫秒
    milvus_use_lite:bool = True # 是否采用轻量级lite运行
    milvus_lite_uri:str = './data/milvus.db' # 轻量级数据库读取路径

    # RAG 配置
    rag_top_k: int = 3
    rag_model: str = "qwen-max"  # 使用快速响应模型，不带扩展思考

    # 文档分块配置
    chunk_max_size: int = 800
    chunk_overlap: int = 100
    max_batch_size:int = 10

    # MCP 服务配置（transport: stdio | sse | streamable-http）
    # 腾讯云托管 MCP 的 URL 通常含 /sse/，需使用 sse；本地 FastMCP 使用 streamable-http
    mcp_cls_transport: str = "streamable-http"
    mcp_cls_url: str = "http://localhost:8003/mcp"
    mcp_monitor_transport: str = "streamable-http"
    mcp_monitor_url: str = "http://localhost:8004/mcp"

    # Prometheus
    prometheus_base_url: str = ""
    prometheus_request_timeout: float = 10.0

    # 自动运维与 Skill
    skills_dir: str = "./skills"
    skill_max_bytes: int = 120_000
    
    # JSON 环境变量示例：{"rag":"rag.service","api":"my-api.service"}
    managed_http_services: dict[str, str] = {}
    service_restart_enabled: bool = False
    service_restart_timeout: int = 30
    service_log_timeout: int = 15
    automation_enabled: bool = True
    automation_alert_poll_interval: int = 60
    automation_patrol_interval: int = 3600
    auto_index_conversations: bool = True
    operation_records_dir: str = "./data/operation_records"

    @property
    def mcp_servers(self) -> dict[str, dict[str, Any]]:
        """获取完整的 MCP 服务器配置"""
        return {
            "cls": {
                "transport": self.mcp_cls_transport,
                "url": self.mcp_cls_url,
            },
            "monitor": {
                "transport": self.mcp_monitor_transport,
                "url": self.mcp_monitor_url,
            }
        }


# 全局配置实例
config = Settings()
