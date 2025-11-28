from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path
from typing import Optional

import typer

from .config import Config
from .gemini_runner import generate_site, refine_site
from .preview import serve_local
from .cloudflare_api import deploy_to_pages, ensure_custom_domain

app = typer.Typer(help="landing-genie - generate and deploy AI landing pages")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@app.command()
def init() -> None:
    """Bootstrap local environment and check config."""
    typer.echo("Initializing landing-genie...")
    try:
        Config.load()
        typer.echo("Config loaded from environment.")
    except RuntimeError as e:
        typer.echo(f"Config error: {e}")
        typer.echo("Create a .env file based on .env.example and try again.")
        raise typer.Exit(code=1)

    sites_dir = _project_root() / "sites"
    sites_dir.mkdir(exist_ok=True)
    (sites_dir / ".gitignore").write_text("*\n!*/\n", encoding="utf-8")
    typer.echo(f"Sites directory ensured at {sites_dir}")


@app.command()
def new(
    prompt: str = typer.Option(..., "--prompt", "-p", help="Product description and target audience"),
    suggested_subdomain: Optional[str] = typer.Option(None, "--suggested-subdomain", "-s"),
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser"),
) -> None:
    """Generate a new landing page with Gemini CLI."""
    config = Config.load()
    root = _project_root()

    slug = suggested_subdomain or typer.prompt("Enter desired subdomain slug (no spaces)")
    slug = slug.strip().lower().replace(" ", "-")

    typer.echo(f"Using slug: {slug}")
    generate_site(slug=slug, product_prompt=prompt, project_root=root, config=config)

    url = serve_local(slug=slug, project_root=root)
    typer.echo(f"Preview URL: {url}")
    if open_browser:
        webbrowser.open(url)

    while True:
        choice = typer.prompt("Happy with this landing? [y]es / [n]o / [f]eedback").lower()
        if choice in {"y", "yes"}:
            typer.echo("Great. You can deploy with: landing-genie deploy {slug}")
            break
        if choice in {"n", "no"}:
            typer.echo("You can rerun `landing-genie new` with a different prompt.")
            break
        if choice in {"f", "feedback"}:
            feedback = typer.prompt("Enter feedback for Gemini (short, focused):")
            refine_site(slug=slug, feedback=feedback, project_root=root, config=config)
            url = serve_local(slug=slug, project_root=root)
            typer.echo(f"Updated preview at: {url}")
            if open_browser:
                webbrowser.open(url)
        else:
            typer.echo("Please answer y, n, or f.")


@app.command()
def deploy(slug: str = typer.Argument(..., help="Slug under sites/ to deploy")) -> None:
    """Deploy an existing landing to Cloudflare Pages."""
    config = Config.load()
    root = _project_root()
    deploy_to_pages(slug=slug, project_root=root, config=config)
    ensure_custom_domain(slug=slug, config=config)


@app.command()
def list() -> None:
    """List generated landing pages under sites/."""
    root = _project_root()
    sites_dir = root / "sites"
    if not sites_dir.exists():
        typer.echo("No sites directory yet. Run `landing-genie init`.")
        raise typer.Exit(code=0)

    slugs = sorted(d.name for d in sites_dir.iterdir() if d.is_dir())
    if not slugs:
        typer.echo("No generated landings yet.")
        return

    typer.echo("Generated landings:")
    for slug in slugs:
        typer.echo(f"- {slug}")


if __name__ == "__main__":
    app()
