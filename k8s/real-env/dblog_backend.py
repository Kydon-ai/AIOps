#!/usr/bin/env python3
"""Small real HTTP service used by the Ubuntu/K8s integration scenarios."""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODE_FILE = Path(os.environ.get("DBLOG_MODE_FILE", "/tmp/dblog-backend.mode"))
RECOVERY_MARKER = MODE_FILE.with_suffix(".recovery-seen")
HOST = os.environ.get("DBLOG_HOST", "0.0.0.0")
PORT = int(os.environ.get("DBLOG_PORT", "8001"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dblog-backend")


def current_mode() -> str:
    try:
        return MODE_FILE.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return "failed"


class Handler(BaseHTTPRequestHandler):
    server_version = "dblog-backend/real-eval"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/api/health":
            self.send_error(404)
            return
        if current_mode() == "degraded":
            log.error("database connection refused; health endpoint is degraded")
            body = json.dumps({"status": "degraded", "service": "dblog-backend", "error": "database connection refused"}).encode()
            self.send_response(503)
        else:
            body = json.dumps({"status": "ok", "service": "dblog-backend"}).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        log.info("http %s", fmt % args)


def fail_fast() -> int:
    try:
        with socket.create_connection(("127.0.0.1", 54321), timeout=0.5):
            pass
    except OSError as exc:
        log.error("database connection refused: %s", exc)
    log.error("process exited with code 1")
    return 1


def main() -> int:
    mode = current_mode()
    # 真实恢复场景第一次启动必须保持 failed；第二次 systemd restart
    # 才切换到 healthy，确保 Agent 能观察到重启前置状态。
    if mode == "failed-recover":
        if RECOVERY_MARKER.exists():
            MODE_FILE.write_text("healthy\n", encoding="utf-8")
            mode = "healthy"
        else:
            RECOVERY_MARKER.write_text("seen\n", encoding="utf-8")
    if mode not in {"healthy", "degraded"}:
        return fail_fast()
    log.info("dblog-backend started in %s mode; health endpoint on %s:%s", mode, HOST, PORT)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
