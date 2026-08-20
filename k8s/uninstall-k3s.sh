#!/usr/bin/env bash
set -euo pipefail

if command -v /usr/local/bin/k3s-uninstall.sh >/dev/null 2>&1; then
  echo "This removes the local K3s cluster and all workloads."
  /usr/local/bin/k3s-uninstall.sh
else
  echo "K3s uninstall script was not found; nothing to remove."
fi
