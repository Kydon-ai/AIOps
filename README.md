# Intelligent On-call

智能on-call项目旨在自动化运维过程，尽可能根据服务日志自动分析，自动解决告警问题，最终达到减轻人力负担，提升个人效率的目的。本项目推荐用于个人服务器运维监控。

运行效果——AI聊天截图
![AI聊天截图](https://github.com/Kydon-ai/Intelligent-On-call/blob/master/assets/ec28ae29-4d34-4634-b577-2b72dde2c287.png)

运行效果——AI排查截图
![AI排查截图](https://github.com/Kydon-ai/Intelligent-On-call/blob/master/assets/ec28ae29-4d34-4634-b577-2b72dde2c287.png)
## 1.快速开始

### 1.1环境安装
环境前提：安装最新版uv和node。
我的版本：uv 0.10.4 (079e3fd05 2026-02-17)、node v22.16.0

uv安装指南：https://uv.doczh.com/getting-started/installation/

node安装指南：https://nvm.uihtm.com/doc/guide.html

docker安装指南：https://github.com/asxez/DockerDesktop-CN/releases

> 直接安装应用就好，*unix则可以添加docker源之后apt安装

### 1.2密钥获取
#### 1.2.1获取腾讯云CLS MCP
前往[腾讯云](https://console.cloud.tencent.com/cam/capi)，创建一个密钥，记住SECRET_ID和SECRET_KEY
创建目录app\envs\8003和目录app\envs\8004，分别放一个相同内容的.env
```env
TRANSPORT=sse
TENCENTCLOUD_SECRET_ID="************"
TENCENTCLOUD_SECRET_KEY="************"
TZ=Asia/Shanghai
PORT=8003 # 一个填8003，一个填8004
```
> 这个项目其实没有实际的日志活动，我们只要跑通，chat过程中能获取到工具就行了

#### 1.2.2配置LLM密钥
前往[阿里百炼](https://bailian.console.aliyun.com/cn-beijing?tab=model#/api-key)，以创建api_key,填写到.env当中


### 1.3依赖安装
#### 1.3.1安装python项目依赖

uv安装依赖：uv sync

#### 1.3.2安装node MCP服务
切换到app\envs\8003，执行命令：
```bash
npx -y cls-mcp-server@latest
```

切换到app\envs\8004，执行命令：
```bash
npx -y cls-mcp-server@latest
```
> 请完成好1.2再执行这一步

### 1.4服务安装

#### 1.4.1安装milvus向量数据库
```powershell
Invoke-WebRequest https://github.com/milvus-io/milvus/releases/download/v3.0.0/milvus-standalone-docker-compose.yml -OutFile docker-compose.yml

docker compose up -d

> 如果使用milvus-lite，请在linux上运行，这样可以不用安装docker版本

```
> 我这是windows的，其他的举一反三

#### 1.4.2安装Prometheus监控工具
```powershell
docker run -d --name prometheus  -p 9090:9090 -v ${PWD}\prometheus.yml:/etc/prometheus/prometheus.yml  -v ${PWD}\alerts.yml:/etc/prometheus/alerts.yml prom/prometheus
```

### 1.5 启动项目

根目录下执行：
```bash
uv run main.py
```

然后打开http://127.0.0.1:9900/，开始聊天就行了

> 可能有些东西没讲到，但是大概率都是小问题了，可以多问问AI就能解决了

## 2.项目结构参考
```bash
.                     
├── README.md
├── app
│   ├── agent
│   │   ├── aiops
│   │   │   ├── __init__.py
│   │   │   ├── executor.py
│   │   │   ├── planner.py
│   │   │   ├── replanner.py
│   │   │   ├── state.py
│   │   │   └── utils.py
│   │   └── mcp_client.py
│   ├── api
│   │   ├── aiops.py
│   │   ├── chat.py
│   │   ├── file.py
│   │   └── health.py
│   ├── config.py
│   ├── core
│   │   └── milvus_client.py
│   ├── envs
│   │   ├── 8003
│   │   └── 8004
│   ├── models
│   │   ├── aiops.py
│   │   ├── request.py
│   │   └── response.py
│   ├── services
│   │   ├── aiops_service.py
│   │   ├── document_splitter_service.py
│   │   ├── rag_agent_service.py
│   │   ├── vector_embedding_service.py
│   │   ├── vector_index_service.py
│   │   ├── vector_search_service.py
│   │   └── vector_store_manager.py
│   ├── tools
│   │   ├── __init__.py
│   │   ├── knowledge_tool.py
│   │   ├── query_metrics_alerts.py
│   │   └── time_tool.py
│   └── utils.py
├── main.py
├── pyproject.toml
├── static
│   ├── app.js
│   ├── index.html
│   └── styles.css
├── uploads
│   └── xxxx.md
└── uv.lock
```

# 说明
本项目仅供个人钻研于学习使用！

## 自动运维配置

应用支持三种运行方式：

1. 用户通过聊天主动请求诊断或处理；
2. 后台每小时执行一次只读巡查；
3. 后台每 60 秒轮询 Prometheus，新进入 `firing` 的告警会触发自动诊断。

自动运维使用本地工具：

- `query_prometheus_alerts`：获取当前 pending/firing 告警；
- `query_prometheus_metrics`：执行只读 PromQL；
- `read_skill`：读取 `skills/<name>/SKILL.md`；
- `read_service_logs`：读取白名单 systemd 服务日志；
- `check_systemd_service`：只读检查 systemd 服务是否存在及当前状态；
- `restart_systemd_service`：仅重启配置白名单中的 systemd 服务。
- `get_docker_containers` / `restart_docker_container`：仅检查和重启受控的 Node Exporter、Blackbox Exporter Docker 容器。

BlogBackendFailed 还提供独立的 systemd MCP 服务，默认地址为
`http://127.0.0.1:8006/mcp`，启动命令为：

```bash
uv run python -m app.mcp_servers.systemd_service
```

该 MCP 提供 `check_systemd_service` 和 `restart_systemd_service`，重启同样受
`MANAGED_HTTP_SERVICES` 与 `SERVICE_RESTART_ENABLED` 保护。

Node Exporter 和 Blackbox Exporter 还提供独立的 Docker MCP 服务，默认地址为
`http://127.0.0.1:8007/mcp`，启动命令为：

```bash
uv run python -m app.mcp_servers.docker_exporter
```

该 MCP 固定执行 `docker ps -a` 查找对应容器，只允许唯一匹配且已停止的
`node_exporter` 或 `blackbox_exporter` 容器重启。Docker 不存在或没有匹配容器时
返回真实错误，不会把 K3s/containerd Pod 当作 Docker 容器。

服务器上建议配置：

```env
PROMETHEUS_BASE_URL=http://127.0.0.1:9090
AUTOMATION_ENABLED=true
AUTOMATION_ALERT_POLL_INTERVAL=60
AUTOMATION_PATROL_INTERVAL=3600
EXPERIENCE_EXTRACTION_ENABLED=true
EXPERIENCE_FILE=./data/通用经验.md
SKILLS_DIR=./skills
DOCKER_MCP_URL=http://127.0.0.1:8007/mcp

# 默认关闭，确认权限和 Skill 完整后再打开
SERVICE_RESTART_ENABLED=false
MANAGED_HTTP_SERVICES='{"rag":"rag.service","8001":"endpoint.service","dblog-backend":"dblog-backend.service"}'
MANAGED_HTTP_GREYLIST='{"demo-test":"demo-test.service"}'
SERVICE_STOP_ENABLED=false
SYSTEMD_MCP_URL=http://127.0.0.1:8006/mcp
```

`MANAGED_HTTP_GREYLIST` 的解析优先级高于 `MANAGED_HTTP_SERVICES`；同名配置以灰名单映射为准。灰名单操作不会绕过安全状态检查：restart 仅在服务处于 `failed/inactive/dead` 时执行，active 服务会返回 skipped；stop 仅对 active 的灰名单服务执行。stop 只接受灰名单服务名，不会对普通白名单服务执行。

生产模式下，Agent 会从 `SYSTEMD_MCP_URL` 加载 `check_systemd_service`、`restart_systemd_service` 和 `stop_systemd_service`；本地 systemd 变更工具不会重复注册。WSL 中的 `systemd-mcp.service` 负责提供该 MCP。

`restart_systemd_service` 使用 `systemctl` 重启白名单中的服务，并检查 `systemctl is-active` 状态。没有 Skill、证据不足或服务不在白名单时，Agent 不应执行重启。该工具不负责 HTTP 健康检查。

白名单校验通过后，工具会先检查服务状态：已处于 `active` 时返回 `restarted=false` 并跳过重启；只有 `failed`、`inactive` 或 `dead` 状态才允许执行重启；状态未知或处于过渡状态时会安全跳过并报告原因。

自动巡查和告警诊断报告只写入 `data/operation_records/`，方便人工审核，不会自动进入向量库。用户对话完成后会由 LLM 判断是否包含可复用经验；只有筛选通过的内容才会追加到 `data/通用经验.md`，并且只对这个文件建立向量索引。

自动运维后台任务应只运行一个应用进程，避免使用多个 Uvicorn workers 导致重复巡查和重复重启。

## 向量文档管理接口

以下接口只操作 Milvus 中的向量，不会删除磁盘上的原始文件：

```text
GET    /api/documents
DELETE /api/documents?source=<完整 source 路径或唯一文件名>
DELETE /api/documents/all?confirm=true
```

`GET /api/documents` 会按来源文件聚合返回分片数量。清空全部向量必须显式传入 `confirm=true`；上传文件或 `data/通用经验.md` 需要重新索引后才能恢复向量。
