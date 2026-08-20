#!/usr/bin/env bash
set -euo pipefail

if ! command -v systemctl >/dev/null 2>&1 || ! systemctl is-system-running >/dev/null 2>&1; then
  echo "WSL systemd is not running; enable systemd in /etc/wsl.conf and restart WSL." >&2
  exit 1
fi

if ! command -v k3s >/dev/null 2>&1; then
  echo "Installing K3s (single-node Kubernetes server)..."
  curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644
else
  echo "K3s is already installed; keeping the existing cluster."
fi

# Keep runtime options in the repository so a fresh WSL setup is reproducible.
# This is applied before the service restart below; it is safe to re-run.
if [ -f "$(dirname "${BASH_SOURCE[0]}")/k3s-config.yaml" ]; then
  sudo install -D -m 0644 "$(dirname "${BASH_SOURCE[0]}")/k3s-config.yaml" /etc/rancher/k3s/config.yaml
fi

# The repository's local pause image keeps pod sandboxes working when Docker
# Hub is unreachable. Build/import it once if it is not already in containerd.
if ! sudo ctr -n k8s.io images ls 2>/dev/null | grep -q 'localhost/pause:3.10'; then
  if command -v buildah >/dev/null 2>&1 && command -v gcc >/dev/null 2>&1; then
    bash "$(dirname "${BASH_SOURCE[0]}")/build-pause-image.sh"
  else
    echo "Missing buildah/gcc; run: sudo apt-get install -y buildah gcc" >&2
    echo "Then run k8s/build-pause-image.sh and re-run this installer." >&2
    exit 1
  fi
fi
sudo systemctl enable k3s
if systemctl is-active --quiet k3s; then
  sudo systemctl restart k3s
else
  sudo systemctl start k3s
fi
sudo k3s kubectl wait --for=condition=Ready node --all --timeout=120s

# Make the kubeconfig available to the regular WSL user as well as root.
if [ "${EUID}" -ne 0 ] && [ -n "${HOME:-}" ]; then
  mkdir -p "${HOME}/.kube"
  sudo cp /etc/rancher/k3s/k3s.yaml "${HOME}/.kube/config"
  sudo chown "$(id -u):$(id -g)" "${HOME}/.kube/config"
  chmod 600 "${HOME}/.kube/config"
fi

echo "K3s is ready:"
sudo k3s kubectl get nodes -o wide
