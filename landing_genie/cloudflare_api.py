"""Cloudflare Pages deployment and DNS helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, cast

import requests

from .config import Config
from .site_paths import normalize_site_dir

API_BASE = "https://api.cloudflare.com/client/v4"
PRODUCTION_BRANCH = "main"
CONTACT_WORKER_NAME_PREFIX = "landing-genie-contact-form"
CONTACT_WORKER_DIR_NAME = "cloudflare/contact-form-worker"
CONTACT_WORKER_ENTRY_POINT = "src/index.js"
CONTACT_WORKER_CONFIG_NAME = "contact-form-worker.toml"
CONTACT_WORKER_COMPATIBILITY_DATE = "2026-01-24"
CONTACT_WORKER_ROUTE_SUFFIX = "/api/contact*"
CONTACT_WORKER_EMAIL_BINDING_NAME = "EMAIL"
LEAD_FROM_LOCAL_PART = "leads"
CONTACT_WORKER_NAME_MAX_LENGTH = 63
_ZONE_CACHE: dict[str, str] = {}


class CloudflareAPIError(RuntimeError):
    """Raised when Cloudflare responds with an error or Wrangler fails."""


def _headers(config: Config) -> Dict[str, str]:
    """Build authorization headers for Cloudflare API requests."""
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
    """Normalize a slug into a safe Cloudflare project segment."""
    out: List[str] = []
    for ch in slug.lower():
        if ch.isalnum() or ch == "-":
            out.append(ch)
        elif ch in {" ", "_", "/"}:
            out.append("-")
    cleaned = "".join(out).strip("-")
    return cleaned or "site"


def _sanitize_domain_for_project(root_domain: str) -> str:
    """Normalize a root domain into a safe project name segment."""
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
    """Build a Cloudflare Pages project name for a slug/domain."""
    slug_part = _sanitize_slug(slug)
    domain_part = _sanitize_domain_for_project(root_domain)
    name = f"lp-{slug_part}-{domain_part}"
    # Cloudflare Pages project name limit is 60 chars
    if len(name) > 60:
        name = name[:60]
    return name


def _contact_worker_name(root_domain: str) -> str:
    """
    Build a deterministic Worker name for the contact form handler.
    """
    domain_part = _sanitize_domain_for_project(root_domain)
    name = f"{CONTACT_WORKER_NAME_PREFIX}-{domain_part}"
    if len(name) > CONTACT_WORKER_NAME_MAX_LENGTH:
        name = name[:CONTACT_WORKER_NAME_MAX_LENGTH]
    return name


def _build_lead_from_address(root_domain: str) -> str:
    """
    Build the sender address for contact form emails.
    """
    return f"{LEAD_FROM_LOCAL_PART}@{root_domain}"


def _validate_lead_to_email(config: Config) -> str:
    """
    Return the configured lead destination email, raising on missing/invalid values.
    """
    lead_to_email = (config.lead_to_email or "").strip()
    if not lead_to_email:
        raise CloudflareAPIError(
            "Missing LEAD_TO_EMAIL. Set it in your .env to enable the contact form email backend."
        )
    if "@" not in lead_to_email or " " in lead_to_email:
        raise CloudflareAPIError(
            "Invalid LEAD_TO_EMAIL. Provide a valid email address (e.g., leads@yourinbox.com)."
        )
    return lead_to_email


def _get_pages_project(project_name: str, config: Config) -> dict[str, Any] | None:
    """
    Return project details if it exists, otherwise None.
    """
    path = f"/accounts/{config.cf_account_id}/pages/projects/{project_name}"
    url = f"{API_BASE}{path}"
    resp = requests.get(url, headers=_headers(config), timeout=60)
    if resp.status_code == 404:
        return None
    try:
        data = resp.json()
    except ValueError:
        raise CloudflareAPIError(
            f"Cloudflare API GET {path} returned non-JSON response: "
            f"{resp.status_code} {resp.text}"
        )
    if not resp.ok or not data.get("success", True):
        raise CloudflareAPIError(
            f"Cloudflare API GET {path} failed: {resp.status_code} {data}"
        )
    return data.get("result", data)


def _ensure_pages_project(project_name: str, config: Config) -> None:
    """
    Create the Pages project if it does not already exist.
    """
    if _get_pages_project(project_name, config):
        return

    path = f"/accounts/{config.cf_account_id}/pages/projects"
    payload = {"name": project_name, "production_branch": PRODUCTION_BRANCH}
    _request("POST", path, config, json=payload)


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
    site_dir = normalize_site_dir(slug, project_root)
    if not site_dir.is_dir():
        raise CloudflareAPIError(f"Site directory does not exist: {site_dir}")

    project_name = _project_name(slug, config.root_domain)

    env = os.environ.copy()
    env["CLOUDFLARE_ACCOUNT_ID"] = config.cf_account_id
    env["CLOUDFLARE_API_TOKEN"] = config.cf_api_token

    # Wrangler prompts to create a project when it does not exist; make that
    # non-interactive by creating it via the API first.
    _ensure_pages_project(project_name, config)

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

    # Command is fully constructed from trusted inputs (slug/domain are sanitized).
    proc = subprocess.run(  # nosec B603
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
# Contact form worker
# ---------------------------------------------------------------------------


def _render_contact_form_worker_config(
    *,
    worker_name: str,
    main_path: Path,
    root_domain: str,
    from_address: str,
    lead_to_email: str,
    turnstile_secret_key: str | None,
) -> str:
    """
    Render a Wrangler configuration for the shared contact form Worker.

    Inputs:
    - worker_name: deterministic name for the Worker.
    - main_path: absolute path to the Worker entrypoint.
    - root_domain: root domain used for routing.
    - from_address: sender address (must be allowed by Email Routing).
    - lead_to_email: destination inbox for submissions.
    - turnstile_secret_key: optional Turnstile secret for bot protection.
    """
    main_path_str = main_path.as_posix()
    config_lines = [
        f'name = "{worker_name}"',
        f'main = "{main_path_str}"',
        f'compatibility_date = "{CONTACT_WORKER_COMPATIBILITY_DATE}"',
        "",
        "[[routes]]",
        f'pattern = "*.{root_domain}{CONTACT_WORKER_ROUTE_SUFFIX}"',
        f'zone_name = "{root_domain}"',
        "",
        "[[send_email]]",
        f'name = "{CONTACT_WORKER_EMAIL_BINDING_NAME}"',
        f'destination_address = "{lead_to_email}"',
        f'allowed_sender_addresses = ["{from_address}"]',
        "",
        "[vars]",
        f'ROOT_DOMAIN = "{root_domain}"',
        f'FROM_ADDRESS = "{from_address}"',
        f'TO_ADDRESS = "{lead_to_email}"',
    ]

    if turnstile_secret_key:
        config_lines.append(f'TURNSTILE_SECRET_KEY = "{turnstile_secret_key}"')

    config_lines.append("")
    return "\n".join(config_lines)


def deploy_contact_form_worker(
    *,
    project_root: Path,
    config: Config,
    debug: bool = False,
) -> str:
    """
    Deploy the shared contact form Worker and route it to all landing subdomains.

    Raises CloudflareAPIError if required configuration is missing or Wrangler
    reports an error.
    """
    root_domain = config.root_domain.strip().lower()
    if not root_domain:
        raise CloudflareAPIError("ROOT_DOMAIN is missing; cannot configure contact form worker.")

    lead_to_email = _validate_lead_to_email(config)
    from_address = _build_lead_from_address(root_domain)
    worker_name = _contact_worker_name(root_domain)

    worker_root = project_root / CONTACT_WORKER_DIR_NAME
    entry_path = (worker_root / CONTACT_WORKER_ENTRY_POINT).resolve()
    if not entry_path.is_file():
        raise CloudflareAPIError(f"Contact form worker entrypoint not found: {entry_path}")

    config_dir = project_root / ".wrangler"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = (config_dir / CONTACT_WORKER_CONFIG_NAME).resolve()

    config_text = _render_contact_form_worker_config(
        worker_name=worker_name,
        main_path=entry_path,
        root_domain=root_domain,
        from_address=from_address,
        lead_to_email=lead_to_email,
        turnstile_secret_key=(os.getenv("TURNSTILE_SECRET_KEY") or "").strip() or None,
    )

    config_path.write_text(config_text, encoding="utf-8")

    env = os.environ.copy()
    env["CLOUDFLARE_ACCOUNT_ID"] = config.cf_account_id
    env["CLOUDFLARE_API_TOKEN"] = config.cf_api_token

    cmd = [
        "npx",
        "wrangler",
        "deploy",
        "--config",
        str(config_path),
    ]

    proc = subprocess.run(  # nosec B603
        cmd,
        env=env,
        capture_output=True,
        text=True,
        cwd=str(worker_root),
    )

    if proc.returncode != 0:
        raise CloudflareAPIError(
            "Wrangler deploy failed for contact form worker "
            f"(exit {proc.returncode}).\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
        )

    if debug:
        print(proc.stdout.strip())

    return worker_name


# ---------------------------------------------------------------------------
# DNS and custom domains
# ---------------------------------------------------------------------------


def _find_zone_id(config: Config) -> str:
    """Find and cache the Cloudflare zone ID for the root domain."""
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

    records: List[Dict[str, Any]] = _request(
        "GET",
        base_path,
        config,
        params={"name": fqdn, "type": "CNAME"},
    )

    existing: Dict[str, Any] | None = records[0] if records else None

    payload: Dict[str, str | bool] = {
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

    domains: List[Dict[str, Any]] = _request("GET", domains_path, config)
    existing: Dict[str, Any] | None = None
    for d in domains:
        if d.get("name") == fqdn:
            existing = d
            break

    domain: Dict[str, Any]
    if existing:
        domain = existing
        print(
            f"Custom domain already configured: {fqdn} "
            f"(status: {domain.get('status')})"
        )
    else:
        domain: Dict[str, Any] = _request(
            "POST", domains_path, config, json={"name": fqdn}
        )
        existing = domain
        print(
            f"Added custom domain: {fqdn} "
            f"(status: {domain.get('status')})"
        )

    pages_hostname = f"{project_name}.pages.dev"
    _ensure_dns_record(fqdn=fqdn, target=pages_hostname, config=config)

    status: str | None = cast(str | None, domain.get("status"))
    if status and status != "active":
        print(
            "Domain verification pending "
            f"(status: {status}). DNS and TLS may take a few minutes to finalize."
        )

    return fqdn
