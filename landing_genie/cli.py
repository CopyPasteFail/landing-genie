from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path
from typing import Optional

import typer

from .config import Config
from .gemini_runner import generate_site, refine_site
from .image_generator import generate_images_for_site
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


@app.command()
def new(
    prompt: str = typer.Option(..., "--prompt", "-p", help="Product description and target audience"),
    suggested_subdomain: Optional[str] = typer.Option(None, "--suggested-subdomain", "-s"),
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser"),
    generate_images: bool = typer.Option(True, "--images/--no-images", help="Generate images with GEMINI_API_KEY after creating the site"),
    overwrite_images: bool = typer.Option(False, "--overwrite-images", help="Regenerate images even if files already exist"),
) -> None:
    """Generate a new landing page with Gemini CLI."""
    config = Config.load()
    root = _project_root()

    slug = suggested_subdomain or typer.prompt("Enter desired subdomain slug (no spaces)")
    slug = slug.strip().lower().replace(" ", "-")

    typer.echo(f"Using slug: {slug}")
    generate_site(slug=slug, product_prompt=prompt, project_root=root, config=config)

    if generate_images:
        api_key_present = config.gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not api_key_present:
            typer.echo("GEMINI_API_KEY not set; skipping image generation.")
        else:
            try:
                created = generate_images_for_site(
                    slug=slug,
                    product_prompt=prompt,
                    project_root=root,
                    config=config,
                    overwrite=overwrite_images,
                )
                if created:
                    typer.echo("Generated images:")
                    for path in created:
                        typer.echo(f"- {path}")
                else:
                    typer.echo("No image placeholders found or images already existed; skipping generation.")
            except Exception as exc:
                typer.echo(f"Image generation skipped: {exc}")

    url = serve_local(slug=slug, project_root=root)
    typer.echo(f"Preview URL: {url}")
    if open_browser:
        webbrowser.open(url)

    while True:
        choice = typer.prompt("Happy with this landing? [y]es / [n]o / [f]eedback").lower()
        if choice in {"y", "yes"}:
            typer.echo(f"Great. You can deploy with: landing-genie deploy {slug}")
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
    project_name = deploy_to_pages(slug=slug, project_root=root, config=config)
    fqdn = ensure_custom_domain(slug=slug, project_name=project_name, config=config)
    typer.echo(f"Live URL: https://{fqdn}")


@app.command()
def images(
    slug: str = typer.Argument(..., help="Slug under sites/ to generate images for"),
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="Product description used to guide the images"),
    overwrite: bool = typer.Option(False, "--overwrite/--keep-existing", help="Regenerate even if image files exist"),
) -> None:
    """Generate images for an existing landing using Gemini's image model."""
    config = Config.load()
    root = _project_root()
    api_key_present = config.gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key_present:
        typer.echo("GEMINI_API_KEY not set; cannot generate images. Export it and retry.")
        raise typer.Exit(code=1)

    product_prompt = prompt or typer.prompt("Enter a short product description to guide the images")

    try:
        created = generate_images_for_site(
            slug=slug,
            product_prompt=product_prompt,
            project_root=root,
            config=config,
            overwrite=overwrite,
        )
    except Exception as exc:
        typer.echo(f"Image generation failed: {exc}")
        raise typer.Exit(code=1)

    if created:
        typer.echo("Generated images:")
        for path in created:
            typer.echo(f"- {path}")
    else:
        typer.echo("No image placeholders found or images already existed; nothing to do.")


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
