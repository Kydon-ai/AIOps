#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCENARIO="${1:-}"
case "${SCENARIO}" in
  healthy|node-exporter-down|blackbox-exporter-down|both-exporters-down|prometheus-down|all-observability-down|blackbox-target-failed|prometheus-node-down|prometheus-blackbox-down|prometheus-target-failed|node-target-failed|blackbox-and-target-failed|prometheus-node-target-failed|prometheus-blackbox-target-failed|node-blackbox-target-failed|all-observability-target-failed|resource-cpu-pressure|resource-memory-pressure|resource-disk-existing-pressure) ;;
  *)
    echo "Usage: $0 {healthy|node-exporter-down|blackbox-exporter-down|both-exporters-down|prometheus-down|all-observability-down|blackbox-target-failed|prometheus-node-down|prometheus-blackbox-down|prometheus-target-failed|node-target-failed|blackbox-and-target-failed|prometheus-node-target-failed|prometheus-blackbox-target-failed|node-blackbox-target-failed|all-observability-target-failed|resource-cpu-pressure|resource-memory-pressure|resource-disk-existing-pressure}" >&2
    exit 2
    ;;
esac

if kubectl get nodes >/dev/null 2>&1; then
  K=(kubectl)
else
  K=(sudo k3s kubectl)
fi
k() { "${K[@]}" "$@"; }

# Applying an overlay does not prune resources that belonged to the previous
# scenario. Remove stale resource-stressor Deployments explicitly so CPU and
# memory pressure cannot leak into the next test.
for stress_deployment in cpu-stressor memory-stressor; do
  if [[ "${SCENARIO}" != "resource-${stress_deployment%-stressor}-pressure" ]]; then
    k -n observability delete deployment "${stress_deployment}" --ignore-not-found >/dev/null
  fi
done

# The overlays include both Deployments, so every load restores the component
# that was down in the previous scenario. The base manifests live outside each
# scenario directory; explicitly allow that read-only reference.
k kustomize --load-restrictor LoadRestrictionsNone "${ROOT_DIR}/k8s/scenarios/${SCENARIO}" | k apply -f -

# Target-failure overlays replace prometheus-config. Restore the checked-in
# baseline for every other scenario so a later healthy/exporter-down case does
# not accidentally keep probing the synthetic 127.0.0.1:19999 target.
if [[ "${SCENARIO}" != *-target-failed ]]; then
  CONFIG_TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "${CONFIG_TMP_DIR}"' EXIT
  sed -e 's/172\.17\.0\.1:9100/127.0.0.1:9100/g' \
      -e 's/172\.17\.0\.1:9115/127.0.0.1:9115/g' \
      "${ROOT_DIR}/data/promethus_config/prometheus.yml" > "${CONFIG_TMP_DIR}/prometheus.yml"
  k -n observability create configmap prometheus-config \
    --from-file="${CONFIG_TMP_DIR}/prometheus.yml" \
    --dry-run=client -o yaml | k apply -f -
fi

# Resource scenarios provide a short-lived test rules ConfigMap. Restore the
# normal rules when leaving one, so later scenarios do not inherit test-only
# thresholds or alert names.
if [[ "${SCENARIO}" != resource-* && "${SCENARIO}" != *-target-failed ]]; then
  k -n observability create configmap prometheus-rules \
    --from-file="${ROOT_DIR}/data/promethus_config/alerts.yml" \
    --dry-run=client -o yaml | k apply -f -
fi

# A ConfigMap mounted with subPath is not reloaded by an existing Prometheus
# process. Restart it for the target-failure scenario so the new scrape target
# becomes active immediately.
PROM_REPLICAS="$(k -n observability get deployment/prometheus -o jsonpath='{.spec.replicas}')"
if [[ "${SCENARIO}" == *-target-failed ]]; then
  # The pod uses hostPort 9090, so a rolling restart cannot schedule the
  # replacement beside the old pod. A short scale-to-zero restart avoids that
  # host-port collision and guarantees the updated subPath ConfigMap is read.
  if [[ "${PROM_REPLICAS:-0}" -gt 0 ]]; then
    k -n observability scale deployment/prometheus --replicas=0
    k -n observability wait --for=delete pod -l app.kubernetes.io/name=prometheus --timeout=120s
    k -n observability scale deployment/prometheus --replicas=1
  fi
elif [[ "${PROM_REPLICAS:-0}" -gt 0 ]]; then
  # The baseline ConfigMap is mounted with subPath, so recreate the pod after
  # restoring it. Scale-to-zero also avoids the hostPort 9090 collision.
  k -n observability scale deployment/prometheus --replicas=0
  k -n observability wait --for=delete pod -l app.kubernetes.io/name=prometheus --timeout=120s
  k -n observability scale deployment/prometheus --replicas=1
fi

# Wait only for components whose desired replica count is non-zero. This makes
# the same loader work for every combination without waiting for an intentionally
# stopped Deployment.
for resource in $(k -n observability get deployment -o name); do
  deployment="${resource#deployment.apps/}"
  replicas="$(k -n observability get deployment "${deployment}" -o jsonpath='{.spec.replicas}')"
  if [[ "${replicas:-0}" -gt 0 ]]; then
    k -n observability rollout status "deployment/${deployment}" --timeout=180s
  fi
done

echo "Loaded scenario: ${SCENARIO}"
k -n observability get deployment,pods -o wide
