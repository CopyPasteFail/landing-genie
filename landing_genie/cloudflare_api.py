from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import requests

from .config import Config

API_BASE = "https://api.cloudflare.com/client/v4"
PRODUCTION_BRANCH = "main"
_ZONE_CACHE: dict[str, str] = {}


class CloudflareAPIError(RuntimeError):
    """Raised when Cloudflare responds with an error or Wrangler fails."""


def _headers(config: Config) -> Dict[str, str]:
    return {"Authorization": f"Bearer {config.cf_api_token}"}


def _request(method: str, path: str, config: Config, **kwargs: Any) -> Any:
    """
    Generic Cloudflare API helper.

    Returns the `result` field on success and raises CloudflareAPIError on
    HTTP error or when `success` is false.
    """
    url = f"{API_BASE}{path}"
    headers = kwargs.pop("headers", {})
    headers.update(_headers(config))

    resp = requests.request(method, url, headers=headers, timeout=60, **kwargs)
    try:
        data = resp.json()
    except ValueError:
        raise CloudflareAPIError(
            f"Cloudflare API {method} {path} returned non-JSON response: "
            f"{resp.status_code} {resp.text}"
        )

    if not resp.ok or not data.get("success", True):
        raise CloudflareAPIError(
            f"Cloudflare API {method} {path} failed: {resp.status_code} {data}"
        )

    return data.get("result", data)


# ---------------------------------------------------------------------------
# Project naming (one Pages project per slug)
# ---------------------------------------------------------------------------


def _sanitize_slug(slug: str) -> str:
    out: List[str] = []
    for ch in slug.lower():
        if ch.isalnum() or ch == "-":
            out.append(ch)
        elif ch in {" ", "_", "/"}:
            out.append("-")
    cleaned = "".join(out).strip("-")
    return cleaned or "site"


def _sanitize_domain_for_project(root_domain: str) -> str:
    out: List[str] = []
    for ch in root_domain.lower():
        if ch.isalnum() or ch == "-":
            out.append(ch)
    cleaned = "".join(out)
    if not cleaned:
        raise CloudflareAPIError(
            "Root domain is empty after sanitizing; cannot form project name"
        )
    return cleaned


def _project_name(slug: str, root_domain: str) -> str:
    slug_part = _sanitize_slug(slug)
    domain_part = _sanitize_domain_for_project(root_domain)
    name = f"lp-{slug_part}-{domain_part}"
    # Cloudflare Pages project name limit is 60 chars
    if len(name) > 60:
        name = name[:60]
    return name


# ---------------------------------------------------------------------------
# Deployment via Wrangler (direct upload of folder)
# ---------------------------------------------------------------------------


def deploy_to_pages(slug: str, project_root: Path, config: Config) -> str:
    """
    Deploy sites/<slug>/ to Cloudflare Pages using Wrangler.

    This is equivalent to:
      CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_API_TOKEN=... \
        npx wrangler pages deploy sites/<slug> \
          --project-name=<derived_name> \
          --branch=main

    Returns the Pages project name (used for custom-domain wiring).
    """
    site_dir = project_root / "sites" / slug
    if not site_dir.is_dir():
        raise CloudflareAPIError(f"Site directory does not exist: {site_dir}")

    project_name = _project_name(slug, config.root_domain)

    env = os.environ.copy()
    env["CLOUDFLARE_ACCOUNT_ID"] = config.cf_account_id
    env["CLOUDFLARE_API_TOKEN"] = config.cf_api_token

    # Use npx so you do not have to install wrangler globally;
    # if you prefer a global `wrangler`, just change the command list.
    cmd = [
        "npx",
        "wrangler",
        "pages",
        "deploy",
        str(site_dir),
        f"--project-name={project_name}",
        "--branch",
        PRODUCTION_BRANCH,
    ]

    proc = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
    )

    if proc.returncode != 0:
        raise CloudflareAPIError(
            "Wrangler deploy failed "
            f"(exit {proc.returncode}).\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
        )

    # Optional: show Wrangler output for debugging
    print(proc.stdout.strip())

    return project_name


# ---------------------------------------------------------------------------
# DNS and custom domains
# ---------------------------------------------------------------------------


def _find_zone_id(config: Config) -> str:
    if config.root_domain in _ZONE_CACHE:
        return _ZONE_CACHE[config.root_domain]

    zones = _request(
        "GET",
        "/zones",
        config,
        params={"name": config.root_domain},
    )
    if not zones:
        raise CloudflareAPIError(f"No Cloudflare zone found for {config.root_domain}")
    zone_id = zones[0]["id"]
    _ZONE_CACHE[config.root_domain] = zone_id
    return zone_id


def _ensure_dns_record(*, fqdn: str, target: str, config: Config) -> None:
    """
    Ensure fqdn is a CNAME pointing at target in the root zone.
    """
    zone_id = _find_zone_id(config)
    base_path = f"/zones/{zone_id}/dns_records"

    records = _request(
        "GET",
        base_path,
        config,
        params={"name": fqdn, "type": "CNAME"},
    )

    existing = records[0] if records else None

    payload = {
        "type": "CNAME",
        "name": fqdn,
        "content": target,
        "proxied": True,
    }

    if existing and existing.get("content") == target:
        print(f"DNS already points {fqdn} -> {target}")
        return

    if existing:
        _request("PUT", f"{base_path}/{existing['id']}", config, json=payload)
        print(f"Updated DNS record: {fqdn} -> {target}")
    else:
        _request("POST", base_path, config, json=payload)
        print(f"Created DNS record: {fqdn} -> {target}")


def ensure_custom_domain(*, slug: str, project_name: str, config: Config) -> str:
    """
    Attach slug.root_domain as a custom domain to the given Pages project and
    ensure the DNS CNAME is present.

    Returns the fully qualified domain name.
    """
    fqdn = f"{slug}.{config.root_domain}"
    domains_path = (
        f"/accounts/{config.cf_account_id}/pages/projects/{project_name}/domains"
    )

    domains = _request("GET", domains_path, config)
    existing = None
    for d in domains:
        if d.get("name") == fqdn:
            existing = d
            break

    if existing:
        print(
            f"Custom domain already configured: {fqdn} "
            f"(status: {existing.get('status')})"
        )
    else:
        existing = _request("POST", domains_path, config, json={"name": fqdn})
        print(
            f"Added custom domain: {fqdn} "
            f"(status: {existing.get('status')})"
        )

    pages_hostname = f"{project_name}.pages.dev"
    _ensure_dns_record(fqdn=fqdn, target=pages_hostname, config=config)

    status = (existing or {}).get("status")
    if status and status != "active":
        print(
            "Domain verification pending "
            f"(status: {status}). DNS and TLS may take a few minutes to finalize."
        )

    return fqdn
