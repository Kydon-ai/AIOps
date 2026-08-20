#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${PROM_CONFIG_DIR:-${ROOT_DIR}/data/promethus_config}"
NAMESPACE="observability"

for file in prometheus.yml alerts.yml blackbox.yml; do
  test -f "${CONFIG_DIR}/${file}" || {
    echo "Missing ${CONFIG_DIR}/${file}" >&2
    exit 1
  }
done

if kubectl get nodes >/dev/null 2>&1; then
  K=(kubectl)
else
  K=(sudo k3s kubectl)
fi
k() { "${K[@]}" "$@"; }

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

# The checked-in config is also used by the host-based deployment. Rewrite only
# the Docker-bridge exporter addresses in a temporary copy; source files remain
# unchanged and can continue to be used by other environments.
sed -e 's/172\.17\.0\.1:9100/127.0.0.1:9100/g' \
    -e 's/172\.17\.0\.1:9115/127.0.0.1:9115/g' \
    "${CONFIG_DIR}/prometheus.yml" > "${TMP_DIR}/prometheus.yml"
cp "${CONFIG_DIR}/alerts.yml" "${TMP_DIR}/alerts.yml"
cp "${CONFIG_DIR}/blackbox.yml" "${TMP_DIR}/blackbox.yml"

k apply -f "${ROOT_DIR}/k8s/manifests/namespace.yaml"
k -n "${NAMESPACE}" create configmap prometheus-config \
  --from-file="${TMP_DIR}/prometheus.yml" \
  --dry-run=client -o yaml | k apply -f -
k -n "${NAMESPACE}" create configmap prometheus-rules \
  --from-file="${TMP_DIR}/alerts.yml" \
  --dry-run=client -o yaml | k apply -f -
k -n "${NAMESPACE}" create configmap blackbox-config \
  --from-file="${TMP_DIR}/blackbox.yml" \
  --dry-run=client -o yaml | k apply -f -

k apply -f "${ROOT_DIR}/k8s/manifests/node-exporter.yaml"
k apply -f "${ROOT_DIR}/k8s/manifests/blackbox-exporter.yaml"
k apply -f "${ROOT_DIR}/k8s/manifests/prometheus.yaml"

k -n "${NAMESPACE}" rollout status deployment/node-exporter --timeout=180s
k -n "${NAMESPACE}" rollout status deployment/blackbox-exporter --timeout=180s
k -n "${NAMESPACE}" rollout status deployment/prometheus --timeout=180s

echo "Observability stack is ready on host ports 9100, 9115 and 9090."
k -n "${NAMESPACE}" get pods -o wide
