from __future__ import annotations

import http.server
import socketserver
from pathlib import Path
from threading import Thread
from typing import Any

# Track running preview servers so we can reuse an existing one instead of
# attempting to bind the same port again.
_SERVERS: dict[int, tuple[socketserver.TCPServer, Thread, str, bool]] = {}


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def _stop_server(port: int) -> None:
    server_info = _SERVERS.pop(port, None)
    if not server_info:
        return
    httpd, thread, _, _ = server_info
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=1)


def serve_local(slug: str, project_root: Path, port: int = 4173, debug: bool = False) -> str:
    site_dir = project_root / "sites" / slug
    if not site_dir.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    existing = _SERVERS.get(port)
    if existing:
        _, thread, existing_slug, existing_debug = existing
        if existing_slug == slug and existing_debug == debug and thread.is_alive():
            return f"http://localhost:{port}"
        _stop_server(port)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(site_dir), **kwargs)

        def log_message(self, format: str, *args: Any) -> None:
            # Only log errors unless debug is enabled.
            if not debug:
                try:
                    status = int(args[1])
                except (IndexError, ValueError, TypeError):
                    status = None
                if status is None or status < 400:
                    return
            super().log_message(format, *args)

    httpd = ReusableTCPServer(("", port), Handler)

    def _run() -> None:
        if debug:
            print(f"Serving {site_dir} at http://localhost:{port}")
        httpd.serve_forever()

    thread = Thread(target=_run, daemon=True)
    thread.start()
    _SERVERS[port] = (httpd, thread, slug, debug)
    return f"http://localhost:{port}"
