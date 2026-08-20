---
name: node-exporter-down
description: 处理 NodeExporterDown 或 node-exporter 不可用告警；先收集 Prometheus/Kubernetes 证据，再用受控 Docker 工具查找并按条件重启对应容器。
---

# Node Exporter 故障处理

## 适用范围

仅适用于 `NodeExporterDown`、`node-exporter` 不可用或 node exporter 抓取失败。不要把普通节点 CPU、内存或磁盘告警误当成 exporter 故障。

## 固定诊断流程

必须先完成只读证据收集，调用顺序如下：

1. `query_prometheus_alerts`：确认告警名称、状态、实例、持续时间和当前是否仍为 `pending/firing`。
2. `query_prometheus_metrics`：查询与 node exporter 相关的 `up`、`node_exporter` 或抓取指标，记录真实返回。
3. `get_kubernetes_deployments(namespace="observability")`：确认 `node-exporter` 的 desired、ready、available 副本。
4. `get_kubernetes_pods(namespace="observability")`：确认 Pod phase、容器 ready、重启次数和最近状态。
5. `get_kubernetes_events(namespace="observability")`：确认是否有调度、拉取镜像、缩容或容器退出事件。

如果 Kubernetes 证据显示 Deployment/Pod 正常，不得直接断言 exporter 宕机；继续区分 Prometheus 抓取链路、网络和目标节点问题。

## Docker 自动恢复

只有在告警仍未恢复且上述证据支持 exporter 不可用时，才调用：

6. `get_docker_containers(service_name="node_exporter")`：该正式工具内部固定执行 `docker ps -a`。
7. 如果返回**唯一**对应容器，且状态不是 `running`，调用 `restart_docker_container(service_name="node_exporter")`。
8. 如果 Docker 不可用、找不到容器、找到多个容器或容器已经运行：停止自动重启，原样记录原因。当前 K3s/containerd 环境没有 Docker 容器时，这是预期结果，不得伪造重启成功。
9. 重启成功后再次调用 `get_docker_containers(service_name="node_exporter")`，并重新查询告警/抓取指标确认恢复。

不得执行 `shell`、`docker exec`、`docker rm`、`docker run`、`kill`、`pkill`，不得重启任意未匹配的容器，也不得修改 K8s Deployment。

## 报告要求

调用 `save_warning_log`，使用 `warning_type="node_exporter_down"`，报告必须包含：告警原文、Prometheus 指标、Kubernetes 副本/Pod/事件、`docker ps -a` 的真实结果、是否执行 Docker 重启、重启后复核和后续建议。

如果 Docker 不可用或没有对应容器，明确写“未执行 Docker 重启及原因”，不要把 K8s 中的 containerd Pod 当成 Docker 容器。
