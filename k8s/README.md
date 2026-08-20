# WSL K3s 监控故障演练

本目录提供一个单节点 K3s 集群中的 Prometheus、Node Exporter 和 Blackbox Exporter，以及两个可重复加载的故障场景。

## 一次性安装

在 WSL Ubuntu 中执行：

```bash
cd /mnt/c/Users/lqd/D/VSCode/FILE/xiaolin/rag
sudo apt-get update && sudo apt-get install -y buildah gcc
bash k8s/install-k3s.sh
bash k8s/install-observability.sh
```

`install-k3s.sh` 只安装/启动 K3s（并构建一个本地静态 pause 镜像，避免 Docker Hub 网络问题）；如果 K3s 已存在会跳过。`install-observability.sh` 会从
`/mnt/c/Users/lqd/D/VSCode/FILE/xiaolin/rag/data/promethus_config` 读取三个配置文件并创建 ConfigMap。

安装完成后：

```bash
curl http://127.0.0.1:9090/-/ready
curl http://127.0.0.1:9100/metrics | head
curl http://127.0.0.1:9115/-/healthy
kubectl -n observability exec deploy/prometheus -- id   # uid=0(root)
```

Prometheus 配置中的 exporter 地址会在加载时将 `172.17.0.1:9100/9115` 映射到
`127.0.0.1:9100/9115`，不会修改源配置文件；原有应用健康检查目标保持不变。

## 加载故障场景

场景目录是完整的期望状态文件。一次加载会自动 reconcile Node Exporter、Blackbox Exporter 和 Prometheus 三个 Deployment；不需要逐个执行 `kubectl scale` 或手动启动服务。每次加载都会恢复未故障组件，因此场景之间不会互相污染：

```bash
bash k8s/load-scenario.sh node-exporter-down
bash k8s/load-scenario.sh blackbox-exporter-down
bash k8s/load-scenario.sh healthy
```

可用场景还包括：

```text
both-exporters-down      Node Exporter 与 Blackbox Exporter 同时停止
prometheus-down          仅 Prometheus 停止
all-observability-down   三个观测组件全部停止
blackbox-target-failed   组件仍运行，但 Blackbox 目标改为不可达地址
```

每次执行 `load-scenario.sh` 都会应用该场景的完整 Deployment 期望状态；不需要手动逐个启动服务。场景脚本会等待应当运行的组件就绪，并在需要时重启 Prometheus 读取新的抓取配置。

真实场景验收样例位于 `eval/k8s_scenario_cases.jsonl`，运行：

```bash
/mnt/c/Users/lqd/D/VSCode/FILE/xiaolin/rag/.venv/bin/python eval/run_k8s_scenario_eval.py
```

脚本会依次切换所有场景，检查 Deployment 副本数、Prometheus `up` 和失败目标的 `probe_success`，最后自动恢复 `healthy`，结果写入 `eval/results/`。

告警规则中的 `for` 时间是 2 分钟；测评脚本应等待至少 2 分钟再读取 `/api/v1/alerts`，或直接查询 `up{job="node"}` / `up{job="blackbox"}` 验证即时状态。

PowerShell 用户可以从 Windows 执行：

```powershell
wsl.exe -d Ubuntu-26.04 -- bash -lc "cd /mnt/c/Users/lqd/D/VSCode/FILE/xiaolin/rag && bash k8s/load-scenario.sh node-exporter-down"
```

清理（会卸载 K3s 及其工作负载）前请确认不再需要该本地集群：

```bash
bash k8s/uninstall-k3s.sh
```

## 资源异常场景与真实 Agent 评测

除服务下线/目标失败场景外，还提供三个不会破坏宿主机的资源场景：

- `resource-cpu-pressure`：在 observability 命名空间运行受限的 CPU stressor，并通过 cAdvisor 指标触发 `CpuStressorActive`。
- `resource-memory-pressure`：在 128Mi cgroup 内占用约 96Mi 内存，并通过 cAdvisor 触发 `MemoryStressorHigh`。
- `resource-disk-existing-pressure`：只读监控 `/mnt/c` 当前空间，不写入磁盘；测试阈值为剩余空间小于 25%，触发 `WindowsCDiskLow`。

资源压力 Deployment 会在切换到其他场景时自动删除，测试脚本结束也会恢复 `healthy`。K8s 状态验收：

```bash
/mnt/c/Users/lqd/D/VSCode/FILE/xiaolin/rag/.venv/bin/python eval/run_k8s_scenario_eval.py
```

让真实 Agent 进入每个场景并保存完整工具轨迹：

```bash
/mnt/c/Users/lqd/D/VSCode/FILE/xiaolin/rag/.venv/bin/python eval/run_k8s_agent_eval.py
```

该评测器在导入 Agent 前固定 `PROMETHEUS_BASE_URL=http://127.0.0.1:9090`，只注册只读 Kubernetes API、Prometheus HTTP API 和磁盘查询工具；每个结果 JSON 的 `trajectory` 字段包含 AI tool call 及对应 ToolMessage 原始返回值，确保 Agent 查询的就是当前 K3s 环境而不是 fixture。
