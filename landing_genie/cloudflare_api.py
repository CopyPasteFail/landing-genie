from __future__ import annotations

import hashlib
import io
import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import requests

from .config import Config

API_BASE = "https://api.cloudflare.com/client/v4"
_ZONE_CACHE: dict[str, str] = {}


class CloudflareAPIError(RuntimeError):
    """Raised when Cloudflare responds with an error."""


def _headers(config: Config) -> dict[str, str]:
    return {"Authorization": f"Bearer {config.cf_api_token}"}


def _request(method: str, path: str, config: Config, **kwargs: Any) -> Any:
    url = f"{API_BASE}{path}"
    headers = kwargs.pop("headers", {})
    headers.update(_headers(config))

    response = requests.request(method, url, headers=headers, timeout=60, **kwargs)
    try:
        data = response.json()
    except ValueError as exc:  # pragma: no cover - only hit on non-JSON responses
        raise CloudflareAPIError(
            f"Cloudflare API {method} {path} failed with status {response.status_code}: {response.text}"
        ) from exc

    if not data.get("success"):
        errors = data.get("errors") or []
        message = "; ".join(err.get("message", "") for err in errors if isinstance(err, dict)) or response.text
        raise CloudflareAPIError(f"Cloudflare API {method} {path} failed ({response.status_code}): {message}")

    return data.get("result")


def _iter_files(site_dir: Path) -> Iterable[Tuple[str, bytes]]:
    """Yield (relative_path, content) tuples for all files under site_dir."""
    for path in sorted(site_dir.rglob("*")):
        if path.is_file():
            rel_path = path.relative_to(site_dir).as_posix()
            yield rel_path, path.read_bytes()


def _build_manifest(site_dir: Path) -> Tuple[Dict[str, str], Dict[str, Tuple[str, io.BytesIO, str]]]:
    manifest: Dict[str, str] = {}
    upload_files: Dict[str, Tuple[str, io.BytesIO, str]] = {}

    for rel_path, content in _iter_files(site_dir):
        digest = hashlib.sha256(content).hexdigest()
        manifest[rel_path] = digest

        mime, _ = mimetypes.guess_type(rel_path)
        upload_files[rel_path] = (rel_path, io.BytesIO(content), mime or "application/octet-stream")

    if not upload_files:
        raise CloudflareAPIError(f"No deployable files found under {site_dir}")

    return manifest, upload_files


def deploy_to_pages(slug: str, project_root: Path, config: Config) -> None:
    site_dir = project_root / "sites" / slug
    if not site_dir.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    manifest, upload_files = _build_manifest(site_dir)
    form_fields = {
        "manifest": json.dumps(manifest, separators=(",", ":")),
        "branch": "production",
        "commit_message": f"Deploy {slug} via landing-genie",
        "commit_dirty": "false",
    }

    path = f"/accounts/{config.cf_account_id}/pages/projects/{config.cf_pages_project}/deployments"
    result = _request("POST", path, config, data=form_fields, files=upload_files)

    deployment_id = result.get("id")
    deployment_url = result.get("url")
    print(f"Deployment created: {deployment_id}")
    if deployment_url:
        print(f"Preview URL: {deployment_url}")
    latest_stage = result.get("latest_stage", {})
    if latest_stage:
        print(f"Status: {latest_stage.get('status')} @ {latest_stage.get('ended_on') or latest_stage.get('started_on')}")


def _get_zone_id(config: Config) -> str:
    if config.root_domain in _ZONE_CACHE:
        return _ZONE_CACHE[config.root_domain]

    params = {"name": config.root_domain, "status": "active"}
    result = _request("GET", "/zones", config, params=params)
    if not result:
        raise CloudflareAPIError(
            f"Cloudflare zone for {config.root_domain} not found. Ensure the domain is in your account."
        )

    zone_id = result[0].get("id")
    if not zone_id:
        raise CloudflareAPIError(f"Cloudflare zone id missing for {config.root_domain}")

    _ZONE_CACHE[config.root_domain] = zone_id
    return zone_id


def _ensure_dns_record(fqdn: str, target: str, config: Config) -> None:
    zone_id = _get_zone_id(config)
    params = {"name": fqdn, "type": "CNAME"}
    existing_records = _request("GET", f"/zones/{zone_id}/dns_records", config, params=params)
    existing = existing_records[0] if existing_records else None

    payload = {"type": "CNAME", "name": fqdn, "content": target, "proxied": True, "ttl": 1}

    if existing:
        if existing.get("content") == target and existing.get("type") == "CNAME":
            print(f"DNS already points {fqdn} -> {target}")
            return

        record_id = existing.get("id")
        _request("PUT", f"/zones/{zone_id}/dns_records/{record_id}", config, json=payload)
        print(f"Updated DNS CNAME: {fqdn} -> {target}")
    else:
        _request("POST", f"/zones/{zone_id}/dns_records", config, json=payload)
        print(f"Created DNS CNAME: {fqdn} -> {target}")


def ensure_custom_domain(slug: str, config: Config) -> None:
    fqdn = f"{slug}.{config.root_domain}"
    domains_path = f"/accounts/{config.cf_account_id}/pages/projects/{config.cf_pages_project}/domains"

    domains = _request("GET", domains_path, config) or []
    existing = next((d for d in domains if d.get("name") == fqdn), None)

    if existing:
        print(f"Custom domain already configured: {fqdn} (status: {existing.get('status')})")
    else:
        existing = _request("POST", domains_path, config, json={"name": fqdn})
        print(f"Added custom domain: {fqdn} (status: {existing.get('status')})")

    pages_hostname = f"{config.cf_pages_project}.pages.dev"
    _ensure_dns_record(fqdn=fqdn, target=pages_hostname, config=config)

    status = (existing or {}).get("status")
    if status and status != "active":
        print(f"Domain verification pending (status: {status}). DNS and TLS may take a few minutes to finalize.")
