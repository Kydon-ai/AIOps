#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE_FILE="${ROOT_DIR}/data/eval_runtime/dblog-backend.mode"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_FILE="${UNIT_DIR}/dblog-backend.service"

install_unit() {
  mkdir -p "${UNIT_DIR}" "$(dirname "${MODE_FILE}")"
  sed "s#REPLACE_REPO#${ROOT_DIR}#g" \
    "${ROOT_DIR}/k8s/real-env/dblog-backend.service" > "${UNIT_FILE}"
  systemctl --user daemon-reload
  systemctl --user enable dblog-backend.service >/dev/null
}

action="${1:-}"
case "${action}" in
  install)
    install_unit
    printf 'failed\n' > "${MODE_FILE}"
    systemctl --user restart dblog-backend.service || true
    ;;
  failed)
    install_unit
    rm -f "${MODE_FILE%.mode}.recovery-seen"
    printf 'failed-recover\n' > "${MODE_FILE}"
    systemctl --user restart dblog-backend.service || true
    ;;
  healthy)
    install_unit
    printf 'healthy\n' > "${MODE_FILE}"
    # The formal restart tool performs the restart in the recovery case.
    ;;
  healthy-start)
    install_unit
    printf 'healthy\n' > "${MODE_FILE}"
    systemctl --user restart dblog-backend.service
    ;;
  degraded)
    install_unit
    printf 'degraded\n' > "${MODE_FILE}"
    systemctl --user restart dblog-backend.service || true
    ;;
  degraded-start)
    install_unit
    printf 'degraded\n' > "${MODE_FILE}"
    systemctl --user restart dblog-backend.service
    ;;
  stop)
    systemctl --user stop dblog-backend.service || true
    ;;
  status)
    systemctl --user show dblog-backend.service --no-pager \
      --property=Id,LoadState,ActiveState,SubState,UnitFileState
    ;;
  *)
    echo "Usage: $0 install|failed|healthy|healthy-start|degraded|degraded-start|stop|status" >&2
    exit 2
    ;;
esac
