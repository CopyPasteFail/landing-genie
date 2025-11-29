from __future__ import annotations

import http.server
import socketserver
from pathlib import Path
from threading import Thread
from typing import Any


def serve_local(slug: str, project_root: Path, port: int = 4173) -> str:
    site_dir = project_root / "sites" / slug
    if not site_dir.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(site_dir), **kwargs)

    def _run() -> None:
        with socketserver.TCPServer(("", port), Handler) as httpd:
            print(f"Serving {site_dir} at http://localhost:{port}")
            httpd.serve_forever()

    thread = Thread(target=_run, daemon=True)
    thread.start()
    return f"http://localhost:{port}"
