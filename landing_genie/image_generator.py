from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional

import requests

from .config import Config


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


def _image_prompt(slot: ImageSlot, product_prompt: str) -> str:
    context = (product_prompt or "").strip()
    name_hint = Path(slot.src).stem.replace("-", " ").replace("_", " ")
    detail = slot.alt or f"{name_hint} for the product landing page"
    prompt_parts = [
        detail,
        "Marketing-ready illustration, no text overlays, keep backgrounds clean.",
    ]
    if context:
        prompt_parts.append(f"Product context: {context}")
    if "hero" in slot.src.lower():
        prompt_parts.append("Wide 16:9 composition suitable for a hero banner.")
    else:
        prompt_parts.append("Cohesive color palette to match the page styling.")
    return " ".join(prompt_parts)


def _request_image(prompt: str, model: str, api_key: str) -> tuple[bytes, Optional[dict]]:
    # Use responseModalities for the Gemini 3 image models (responseMimeType is rejected with
    # INVALID_ARGUMENT on those preview endpoints).
    generation_config = {"responseModalities": ["IMAGE"]}

    resp = requests.post(
        _API_URL.format(model=model),
        params={"key": api_key},
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        },
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini image request failed: {resp.status_code} {resp.text}")

    data = resp.json()
    try:
        part = data["candidates"][0]["content"]["parts"][0]
        inline = part.get("inlineData") or part.get("inline_data")
        if not inline:
            raise KeyError("inlineData")
        image_b64 = inline["data"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected Gemini image response: {data}") from exc

    usage = data.get("usageMetadata")
    return base64.b64decode(image_b64), usage


def generate_images_for_site(
    slug: str,
    product_prompt: str,
    project_root: Path,
    config: Config,
    overwrite: bool = False,
) -> list[Path]:
    api_key = config.gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY to enable Gemini image generation.")

    site_dir = project_root / "sites" / slug
    index_path = site_dir / "index.html"
    if not index_path.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    slots = _discover_image_slots(index_path)
    if not slots:
        return []

    generated: list[Path] = []
    for slot in slots:
        target_path = site_dir / slot.src
        if target_path.exists() and not overwrite:
            continue

        prompt_text = _image_prompt(slot, product_prompt)
        image_bytes, usage = _request_image(prompt_text, config.gemini_image_model, api_key)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(image_bytes)
        if usage:
            prompt_tokens = usage.get("promptTokenCount")
            completion_tokens = usage.get("candidatesTokenCount")
            total_tokens = usage.get("totalTokenCount")
            print(
                f"[Gemini Images] Tokens used (model={config.gemini_image_model}): "
                f"prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}"
            )
        generated.append(target_path)

    return generated
