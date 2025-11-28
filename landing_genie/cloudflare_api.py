from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

from .config import Config


def deploy_to_pages(slug: str, project_root: Path, config: Config) -> None:
    # This is intentionally a stub.
    # You will likely want to use the Cloudflare Pages deployment API or wrangler.
    # For now we just print instructions.
    site_dir = project_root / "sites" / slug
    if not site_dir.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    print("TODO: implement deploy_to_pages with Cloudflare API or wrangler.")
    print(f"Would deploy directory: {site_dir}")
    print("See Cloudflare Pages API docs for details.")


def ensure_custom_domain(slug: str, config: Config) -> None:
    # Also a stub. You can fill this in or let Gemini expand it.
    print("TODO: implement ensure_custom_domain via Cloudflare API.")
    fqdn = f"{slug}.{config.root_domain}"
    print(f"Target FQDN would be: {fqdn}")
