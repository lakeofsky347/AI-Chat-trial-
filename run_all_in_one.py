from __future__ import annotations

import socket
import threading
import time

import flet as ft
import httpx
import uvicorn

from app.main import app
from clients.flet_client_main import main as client_main


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _is_backend_ready(base_url: str = "http://127.0.0.1:8000") -> bool:
    try:
        resp = httpx.get(f"{base_url}/api/settings", timeout=1.5)
    except Exception:
        return False
    return resp.status_code == 200


def _run_backend() -> None:
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    server.run()


def main() -> None:
    if _is_port_open("127.0.0.1", 8000):
        if not _is_backend_ready():
            raise RuntimeError(
                "Port 8000 is occupied by another process. "
                "Stop that process or run this app on a clean port."
            )
    else:
        backend_thread = threading.Thread(target=_run_backend, daemon=True)
        backend_thread.start()

        deadline = time.time() + 12
        while time.time() < deadline:
            if _is_backend_ready():
                break
            time.sleep(0.15)
        else:
            raise RuntimeError("Backend failed to become ready within 12 seconds.")

    ft.run(client_main, view=ft.AppView.FLET_APP)


if __name__ == "__main__":
    main()
