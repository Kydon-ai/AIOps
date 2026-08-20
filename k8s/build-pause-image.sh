#!/usr/bin/env bash
set -euo pipefail

# Build a tiny static sandbox image locally. This avoids relying on Docker Hub
# or a third-party pause image when the WSL network cannot reach those hosts.
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
cat > "${TMP_DIR}/pause.c" <<'EOF'
#include <signal.h>
#include <unistd.h>

int main(void) {
  for (;;) pause();
}
EOF
gcc -static -O2 -s -o "${TMP_DIR}/pause" "${TMP_DIR}/pause.c"
cat > "${TMP_DIR}/Dockerfile" <<'EOF'
FROM scratch
COPY pause /pause
ENTRYPOINT ["/pause"]
EOF

sudo buildah bud --isolation chroot -f "${TMP_DIR}/Dockerfile" -t local/pause:3.10 "${TMP_DIR}"
sudo buildah push local/pause:3.10 "oci-archive:${TMP_DIR}/pause.tar:local/pause:3.10"
sudo ctr -n k8s.io images import "${TMP_DIR}/pause.tar"
sudo ctr -n k8s.io images tag local/pause:3.10 localhost/pause:3.10
echo "Built and imported local/pause:3.10 into K3s containerd"
