from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from typing import Optional

import typer

from .config import Config
from .gemini_runner import (
    generate_site,
    refine_site,
    suggest_follow_up_questions,
    suggest_image_follow_up_questions,
)
from .image_generator import (
    ensure_placeholder_assets,
    generate_image_prompts_for_site,
    generate_images_for_site,
)
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
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="Product description and target audience"),
    suggested_subdomain: Optional[str] = typer.Option(None, "--suggested-subdomain", "-s"),
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser"),
    generate_images: bool = typer.Option(True, "--images/--no-images", help="Generate images with GEMINI_API_KEY after creating the site"),
    overwrite_images: bool = typer.Option(False, "--overwrite-images", help="Regenerate images even if files already exist"),
    ask_follow_ups: bool = typer.Option(True, "--follow-ups/--no-follow-ups", help="Ask Gemini for clarifying questions before generation"),
    ask_image_follow_ups: bool = typer.Option(True, "--image-follow-ups/--no-image-follow-ups", help="Ask Gemini for image-specific clarifications before generation"),
    debug: bool = typer.Option(False, "--debug", help="Print prompts sent to Gemini CLI"),
) -> None:
    """Generate a new landing page with Gemini CLI."""
    config = Config.load()
    root = _project_root()

    slug_input = suggested_subdomain if suggested_subdomain is not None else typer.prompt("Enter desired subdomain slug (no spaces)")
    slug = slug_input.strip().lower().replace(" ", "-")

    prompt_input = prompt if prompt is not None else typer.prompt("Enter a product description and target audience")
    prompt_clean = prompt_input.strip()
    if not prompt_clean:
        typer.echo("A prompt is required to generate a landing page.")
        raise typer.Exit(code=1)
    product_prompt: str = prompt_clean

    typer.echo(f"Using slug: {slug}")
    follow_up_context: Optional[str] = None
    image_follow_up_context: Optional[str] = None
    questions: list[str] = []
    image_questions: list[str] = []

    prompt_log_dir = root / ".log"
    prompt_log_dir.mkdir(parents=True, exist_ok=True)
    prompt_log_path = prompt_log_dir / "gemini_prompts.log"
    os.environ["LANDING_GENIE_PROMPT_LOG_PATH"] = str(prompt_log_path)
    typer.echo(f"Gemini prompts will be logged to {prompt_log_path}")

    if ask_follow_ups is False and ask_image_follow_ups:
        typer.echo("Skipping image follow-ups because text follow-ups were disabled.")
        ask_image_follow_ups = False

    if ask_follow_ups:
        try:
            questions = suggest_follow_up_questions(product_prompt=product_prompt, project_root=root, config=config, debug=debug)
        except Exception as exc:
            typer.echo(f"Could not fetch follow-up questions from Gemini; continuing without them. ({exc})")

    if questions:
        total = len(questions)
        label = "clarification" if total == 1 else "clarifications"
        typer.echo(f"Gemini suggests {total} {label}. Press Enter to skip any question.")
        answers: list[tuple[str, str]] = []
        for idx, question in enumerate(questions, start=1):
            q_text = question.strip() or f"Question {idx}"
            typer.echo(f"Q{idx} (out of {total}): {q_text}")
            response = typer.prompt("Answer", default="", show_default=False).strip()
            if response:
                answers.append((q_text, response))
        if answers:
            follow_up_context = "\n".join(f"- {q} Answer: {a}" for q, a in answers)

    if ask_image_follow_ups:
        try:
            image_questions = suggest_image_follow_up_questions(
                product_prompt=product_prompt, project_root=root, config=config, debug=debug
            )
        except Exception as exc:
            typer.echo(f"Could not fetch image follow-up questions from Gemini; continuing without them. ({exc})")

    if image_questions:
        total = len(image_questions)
        label = "clarification" if total == 1 else "clarifications"
        typer.echo(f"Gemini suggests {total} image {label}. Press Enter to skip any question.")
        image_answers: list[tuple[str, str]] = []
        for idx, question in enumerate(image_questions, start=1):
            q_text = question.strip() or f"Image question {idx}"
            typer.echo(f"Image Q{idx} (out of {total}): {q_text}")
            response = typer.prompt("Answer", default="", show_default=False).strip()
            if response:
                image_answers.append((q_text, response))
        if image_answers:
            image_follow_up_context = "\n".join(f"- {q} Answer: {a}" for q, a in image_answers)

    generate_site(
        slug=slug,
        product_prompt=product_prompt,
        project_root=root,
        config=config,
        follow_up_context=follow_up_context,
        include_follow_up_context=ask_follow_ups,
        debug=debug,
    )

    placeholder_created: list[Path] = []
    generated_images: list[Path] = []
    image_prompts: list[tuple[str, str]] = []

    if generate_images:
        api_key_present = config.gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not api_key_present:
            typer.echo("GEMINI_API_KEY not set; skipping image generation.")
        else:
            try:
                generated_images = generate_images_for_site(
                    slug=slug,
                    product_prompt=product_prompt,
                    project_root=root,
                    config=config,
                    overwrite=overwrite_images,
                    image_follow_up_context=image_follow_up_context,
                    debug=debug,
                )
                if generated_images:
                    typer.echo("Generated images:")
                    for path in generated_images:
                        typer.echo(f"- {path}")
                else:
                    typer.echo("No image placeholders found or images already existed; skipping generation.")
            except Exception as exc:
                typer.echo(f"Image generation skipped: {exc}")
    else:
        try:
            image_prompts = generate_image_prompts_for_site(
                slug=slug,
                product_prompt=product_prompt,
                project_root=root,
                config=config,
                image_follow_up_context=image_follow_up_context,
                debug=debug,
            )
            if image_prompts:
                typer.echo("Image prompts generated (not sent to Gemini image model)")
                # for src, prompt_text in image_prompts:
                #     typer.echo(f"- {src}: {prompt_text}")
            else:
                typer.echo("No image placeholders found to generate prompts.")
        except Exception as exc:
            typer.echo(f"Image prompt generation skipped: {exc}")
    # Always ensure placeholders for any remaining referenced assets.
    placeholder_created = ensure_placeholder_assets(slug=slug, project_root=root)
    if placeholder_created:
        typer.echo("Placeholder assets added:")
        for path in placeholder_created:
            typer.echo(f"- {path}")

    url = serve_local(slug=slug, project_root=root, config=config, debug=debug)
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
            feedback = typer.prompt("Enter feedback for Gemini (short, focused)")
            typer.echo("Stage 1/2: sending feedback to Gemini and regenerating the site...")
            refine_site(slug=slug, feedback=feedback, project_root=root, config=config, debug=debug)
            typer.echo("Stage 2/2: refreshing the local preview server...")
            placeholder_created = ensure_placeholder_assets(slug=slug, project_root=root)
            if placeholder_created:
                typer.echo("Placeholder assets added:")
                for path in placeholder_created:
                    typer.echo(f"- {path}")
            url = serve_local(slug=slug, project_root=root, config=config, debug=debug)
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


@app.command(name="list")
def list_sites() -> None:
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
