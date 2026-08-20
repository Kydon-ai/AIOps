---
name: blackbox-exporter-down
description: 处理 BlackboxExporterDown 或 blackbox-exporter 不可用告警；先区分 exporter 故障与目标探针失败，再按条件检查和重启对应 Docker 容器。
---

# Blackbox Exporter 故障处理

## 适用范围

仅适用于 `BlackboxExporterDown`、blackbox exporter 无法抓取或 exporter 自身不可用。若只有 `BlackboxTargetFailed`/`probe_success=0` 而 exporter Deployment/Pod 正常，故障属于被探测目标，不得重启 exporter。

## 固定诊断流程

必须先完成只读证据收集，调用顺序如下：

1. `query_prometheus_alerts`：确认 `BlackboxExporterDown` 与 `BlackboxTargetFailed` 的当前状态，记录实例、目标、持续时间和严重级别。
2. `query_prometheus_metrics`：查询 `probe_success`、blackbox exporter 的 `up`/抓取指标，区分 exporter 本身与目标接口。
3. `get_kubernetes_deployments(namespace="observability")`：确认 `blackbox-exporter` 的 desired、ready、available 副本。
4. `get_kubernetes_pods(namespace="observability")`：确认 Pod phase、容器 ready、重启次数和最近状态。
5. `get_kubernetes_events(namespace="observability")`：确认调度、镜像、探针或容器退出事件。

如果 Deployment/Pod 正常而 `probe_success=0`，必须报告目标接口/网络/证书可能异常，停止 exporter 重启。不能只凭目标失败断言 blackbox exporter 宕机。

## Docker 自动恢复

只有在 `BlackboxExporterDown` 仍为 `pending/firing`，并且 Kubernetes/Prometheus 证据支持 exporter 自身异常时，才调用：

6. `get_docker_containers(service_name="blackbox_exporter")`：该正式工具内部固定执行 `docker ps -a`。
7. 如果返回**唯一**对应容器，且状态不是 `running`，调用 `restart_docker_container(service_name="blackbox_exporter")`。
8. 如果 Docker 不可用、找不到容器、找到多个容器或容器已经运行：停止自动重启并原样记录原因。K3s/containerd 中没有 Docker 容器时，不得伪造恢复结果。
9. 重启成功后再次调用 `get_docker_containers(service_name="blackbox_exporter")`，并重新查询告警、`probe_success` 和 exporter 状态进行复核。

不得执行 `shell`、`docker exec`、`docker rm`、`docker run`、`kill`、`pkill`，不得重启目标业务容器或任意未匹配的 Docker 容器，也不得把目标探针失败当成 exporter 重启条件。

## 报告要求

调用 `save_warning_log`，使用 `warning_type="blackbox_exporter_down"`，报告必须包含：两类告警的区别、`probe_success`/抓取指标、Kubernetes 副本/Pod/事件、`docker ps -a` 的真实结果、是否执行 Docker 重启、重启后复核和后续建议。

如果实际是 `BlackboxTargetFailed` 而不是 exporter 故障，明确写“未执行 exporter 重启”，并说明需要检查目标接口或网络。
