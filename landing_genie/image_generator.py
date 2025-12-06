from __future__ import annotations

import base64
import os
import importlib.resources as resources
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, TypedDict, cast

import requests
import re

from .config import Config
from .site_paths import normalize_site_dir


_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


@dataclass
class ImageSlot:
    src: str
    alt: str


class _ImgParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.slots: list[ImageSlot] = []

    def handle_starttag(self, tag: str, attrs: Iterable[tuple[str, str | None]]) -> None:
        if tag != "img":
            return
        attr_dict = dict(attrs)
        src = attr_dict.get("src")
        if not src or not src.startswith("assets/"):
            return
        alt = (attr_dict.get("alt") or "").strip()
        self.slots.append(ImageSlot(src=src, alt=alt))


def _discover_image_slots(index_path: Path) -> list[ImageSlot]:
    parser = _ImgParser()
    parser.feed(index_path.read_text(encoding="utf-8"))

    seen: set[str] = set()
    unique: list[ImageSlot] = []
    for slot in parser.slots:
        if slot.src in seen:
            continue
        seen.add(slot.src)
        unique.append(slot)
    return unique


_ASSET_PATTERN = re.compile(r"assets/[A-Za-z0-9._/-]+")


def _discover_asset_paths(site_dir: Path) -> set[str]:
    """Find all asset file references (HTML, CSS, JS) under the site dir."""
    assets: set[str] = set()
    for name in ("index.html", "styles.css", "main.js"):
        path = site_dir / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assets.update(_ASSET_PATTERN.findall(text))
    return assets


def _placeholder_bytes(ext: str) -> bytes:
    filename = 'placeholder.jpg' if ext in {'.jpg', '.jpeg'} else 'placeholder.png'
    return resources.files(__package__).joinpath('placeholders').joinpath(filename).read_bytes()


def _resolve_image_prompt_for_slot(
    slot: ImageSlot,
    product_prompt: str,
    project_root: Path,
    config: Config,
    *,
    image_follow_up_context: str | None = None,
    debug: bool = False,
) -> str:
    from . import gemini_runner  # Local import to avoid circular dependency.

    return gemini_runner.generate_image_prompt(
        slot_src=slot.src,
        slot_alt=slot.alt,
        product_prompt=product_prompt,
        project_root=project_root,
        config=config,
        follow_up_context=image_follow_up_context,
        debug=debug,
    )


class _PartPayload(TypedDict):
    text: str


class _ContentPayload(TypedDict):
    role: str
    parts: list[_PartPayload]


class _GenerationConfig(TypedDict):
    responseModalities: list[str]


class _UsageMetadata(TypedDict, total=False):
    promptTokenCount: int
    candidatesTokenCount: int
    totalTokenCount: int


class _InlineData(TypedDict):
    data: str


class _PartResponse(TypedDict, total=False):
    inlineData: _InlineData
    inline_data: _InlineData


class _ContentResponse(TypedDict):
    parts: list[_PartResponse]


class _CandidateResponse(TypedDict):
    content: _ContentResponse


class _GenerateContentResponse(TypedDict, total=False):
    candidates: list[_CandidateResponse]
    usageMetadata: _UsageMetadata


def _request_image(prompt: str, model: str, api_key: str) -> tuple[bytes, _UsageMetadata | None]:
    # Use responseModalities for the Gemini 3 image models (responseMimeType is rejected with
    # INVALID_ARGUMENT on those preview endpoints).
    generation_config: _GenerationConfig = {"responseModalities": ["IMAGE"]}

    contents: list[_ContentPayload] = [{"role": "user", "parts": [{"text": prompt}]}]
    payload: dict[str, object] = {"contents": contents, "generationConfig": generation_config}

    resp = requests.post(
        _API_URL.format(model=model),
        params={"key": api_key},
        json=payload,
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini image request failed: {resp.status_code} {resp.text}")

    data = cast(_GenerateContentResponse, resp.json())
    try:
        candidates = data.get("candidates")
        if not candidates:
            raise KeyError("candidates")
        part = candidates[0]["content"]["parts"][0]
        inline = part.get("inlineData") or part.get("inline_data")
        if not inline:
            raise KeyError("inlineData")
        image_b64 = inline["data"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected Gemini image response: {data}") from exc

    usage = data.get("usageMetadata")
    return base64.b64decode(image_b64), usage


def ensure_placeholder_assets(slug: str, project_root: Path) -> list[Path]:
    """Create lightweight placeholder files for any referenced assets that don't exist."""
    site_dir = normalize_site_dir(slug, project_root)
    if not site_dir.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    assets = _discover_asset_paths(site_dir)
    created: list[Path] = []
    for rel_path in assets:
        path = site_dir / rel_path
        if path.exists():
            try:
                # Gemini sometimes leaves zero-byte placeholder files; treat them as missing.
                if path.stat().st_size > 0:
                    continue
            except OSError:
                # If we cannot stat the file, fall back to recreating it as a placeholder.
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        ext = path.suffix.lower()
        data = _placeholder_bytes(ext)
        path.write_bytes(data)
        created.append(path)
    return created


def generate_image_prompts_for_site(
    slug: str,
    product_prompt: str,
    project_root: Path,
    config: Config,
    image_follow_up_context: str | None = None,
    debug: bool = False,
) -> list[tuple[str, str]]:
    """
    Build image prompts for each asset slot without calling the image generation model.
    Returns a list of (asset_path, prompt_text) pairs.
    """
    site_dir = normalize_site_dir(slug, project_root)
    index_path = site_dir / "index.html"
    if not index_path.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    slots = _discover_image_slots(index_path)
    if not slots:
        return []

    def _slot_alt(slot: ImageSlot) -> str:
        alt_clean = slot.alt.strip() if slot.alt else ""
        if alt_clean:
            return alt_clean
        return Path(slot.src).stem.replace("-", " ").replace("_", " ")

    slots_payload = [{"src": slot.src, "alt": _slot_alt(slot)} for slot in slots]
    from . import gemini_runner  # Local import to avoid circular dependency.

    prompts_map = gemini_runner.generate_image_prompts_batch(
        slots_payload,
        product_prompt,
        project_root,
        config,
        follow_up_context=image_follow_up_context,
        debug=debug,
    )

    prompts: list[tuple[str, str]] = []
    for slot in slots:
        prompt_text = prompts_map.get(slot.src)
        if not prompt_text:
            prompt_text = _resolve_image_prompt_for_slot(
                slot,
                product_prompt,
                project_root,
                config,
                image_follow_up_context=image_follow_up_context,
                debug=debug,
            )
        prompts.append((slot.src, prompt_text))

    return prompts


def generate_images_for_site(
    slug: str,
    product_prompt: str,
    project_root: Path,
    config: Config,
    overwrite: bool = False,
    image_follow_up_context: str | None = None,
    debug: bool = False,
) -> list[Path]:
    api_key = config.gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY to enable Gemini image generation.")

    site_dir = normalize_site_dir(slug, project_root)
    index_path = site_dir / "index.html"
    if not index_path.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    slots = _discover_image_slots(index_path)
    if not slots:
        return []

    prompts_list = generate_image_prompts_for_site(
        slug=slug,
        product_prompt=product_prompt,
        project_root=project_root,
        config=config,
        image_follow_up_context=image_follow_up_context,
        debug=debug,
    )
    prompts_map = {src: prompt for src, prompt in prompts_list}

    generated: list[Path] = []
    for slot in slots:
        target_path = site_dir / slot.src
        if target_path.exists() and not overwrite:
            continue

        prompt_text = prompts_map.get(slot.src)
        if not prompt_text:
            prompt_text = _resolve_image_prompt_for_slot(
                slot,
                product_prompt,
                project_root,
                config,
                image_follow_up_context=image_follow_up_context,
                debug=debug,
            )
        image_bytes, usage = _request_image(prompt_text, config.gemini_image_model, api_key)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(image_bytes)
        if usage:
            prompt_tokens = usage.get("promptTokenCount")
            completion_tokens = usage.get("candidatesTokenCount")
            total_tokens = usage.get("totalTokenCount")

            message = (
                f"[Gemini Images] Tokens used (model={config.gemini_image_model}): "
                f"prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}"
            )

            total = total_tokens
            if total is None and (prompt_tokens is not None or completion_tokens is not None):
                total = (prompt_tokens or 0) + (completion_tokens or 0)

            if config.gemini_image_cost_per_1k_tokens is not None and total is not None:
                estimated_cost = (total / 1000.0) * config.gemini_image_cost_per_1k_tokens
                message += f", estimated_cost={estimated_cost:.6f} USD"

            print(message)
        generated.append(target_path)

    return generated
