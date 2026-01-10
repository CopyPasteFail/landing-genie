"""Image generation and asset utilities."""

from __future__ import annotations

import base64
import json
import hashlib
import importlib.resources as resources
import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, TypedDict, cast

import requests

from .config import Config
from .site_paths import normalize_site_dir


_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


@dataclass
class ImageSlot:
    """Image slot metadata extracted from site HTML."""
    src: str
    alt: str


class _ImgParser(HTMLParser):
    """HTML parser that collects image slots."""
    def __init__(self) -> None:
        """Initialize parser state."""
        super().__init__()
        self.slots: list[ImageSlot] = []

    def handle_starttag(self, tag: str, attrs: Iterable[tuple[str, str | None]]) -> None:
        """Collect asset-backed img tags."""
        if tag != "img":
            return
        attr_dict = dict(attrs)
        src = attr_dict.get("src")
        if not src or not src.startswith("assets/"):
            return
        alt = (attr_dict.get("alt") or "").strip()
        self.slots.append(ImageSlot(src=src, alt=alt))


def _discover_image_slots(index_path: Path) -> list[ImageSlot]:
    """Parse an index file and return unique image slots."""
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
# Update these hashes if placeholder assets change.
_PLACEHOLDER_HASHES = {
    ".png": "2b49ed28439edd7bb0a55d82812e8e88b01b36c2433de346f2affa0ce2e1e22d",
    ".jpg": "2a529eb91c32586932397e67140b475fe222d21e85e3fc37231f616dc685ea91",
    ".jpeg": "2a529eb91c32586932397e67140b475fe222d21e85e3fc37231f616dc685ea91",
}


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
    """Load bundled placeholder bytes for a given extension."""
    filename = 'placeholder.jpg' if ext in {'.jpg', '.jpeg'} else 'placeholder.png'
    return resources.files(__package__).joinpath('placeholders').joinpath(filename).read_bytes()


def _hash_file(path: Path) -> str:
    """Hash a file with SHA-256."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_image_prompt_for_slot(
    slot: ImageSlot,
    product_prompt: str,
    project_root: Path,
    config: Config,
    *,
    image_follow_up_context: str | None = None,
    debug: bool = False,
) -> str:
    """Generate a prompt for a single image slot via Gemini."""
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
    text: str


class _ContentResponse(TypedDict):
    parts: list[_PartResponse]


class _CandidateResponse(TypedDict):
    content: _ContentResponse


class _GenerateContentResponse(TypedDict, total=False):
    candidates: list[_CandidateResponse]
    usageMetadata: _UsageMetadata


class _InlineDataPayload(TypedDict):
    mimeType: str
    data: str


class _PartPayload(TypedDict, total=False):
    text: str
    inlineData: _InlineDataPayload


class _ContentPayload(TypedDict):
    role: str
    parts: list[_PartPayload]


def _guess_image_mime_type(path: Path) -> str:
    """Return a best-effort MIME type for an image path."""
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".avif": "image/avif",
    }.get(path.suffix.lower(), "image/png")


def _strip_code_fences(text: str) -> str:
    """Remove Markdown code fences around text."""
    match = re.match(r"\s*```(?:json)?\s*(.*?)\s*```\s*$", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text.strip()


def _format_reference_prompt(prompt: str, canonical_description: str | None) -> str:
    """Prefix prompts with reference-image guidance."""
    prefix = (
        "Use the provided reference image as the exact product; preserve its shape, "
        "colors, and branding."
    )
    if canonical_description:
        return f"{prefix}\nCanonical product description: {canonical_description}\n{prompt}"
    return f"{prefix} {prompt}"


def _log_image_usage(usage: _UsageMetadata | None, config: Config, *, label: str = "Gemini Images") -> None:
    """Log token usage and estimated image costs."""
    if not usage:
        return

    prompt_tokens = usage.get("promptTokenCount")
    completion_tokens = usage.get("candidatesTokenCount")
    total_tokens = usage.get("totalTokenCount")

    message = (
        f"[{label}] Tokens used (model={config.gemini_image_model}): "
        f"prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}"
    )

    total = total_tokens
    if total is None and (prompt_tokens is not None or completion_tokens is not None):
        total = (prompt_tokens or 0) + (completion_tokens or 0)

    input_cost = None
    output_cost = None
    if config.gemini_image_input_cost_per_1k_tokens is not None and prompt_tokens is not None:
        input_cost = (prompt_tokens / 1000.0) * config.gemini_image_input_cost_per_1k_tokens
    if config.gemini_image_cost_per_1k_tokens is not None and completion_tokens is not None:
        output_cost = (completion_tokens / 1000.0) * config.gemini_image_cost_per_1k_tokens

    estimated_cost = None
    if input_cost is not None or output_cost is not None:
        estimated_cost = (input_cost or 0.0) + (output_cost or 0.0)
    elif config.gemini_image_cost_per_1k_tokens is not None and total is not None:
        estimated_cost = (total / 1000.0) * config.gemini_image_cost_per_1k_tokens

    if estimated_cost is not None:
        message += f", estimated_cost={estimated_cost:.6f} USD"

    print(message)


def _request_image(
    prompt: str,
    model: str,
    api_key: str,
    *,
    reference_image: bytes | None = None,
    reference_mime_type: str | None = None,
) -> tuple[bytes, _UsageMetadata | None]:
    """Request an image from Gemini for the provided prompt."""
    # Use responseModalities for the Gemini 3 image models (responseMimeType is rejected with
    # INVALID_ARGUMENT on those preview endpoints).
    generation_config: _GenerationConfig = {"responseModalities": ["IMAGE"]}

    parts: list[_PartPayload] = []
    if reference_image is not None:
        mime_type = reference_mime_type or "image/png"
        parts.append(
            {
                "inlineData": {
                    "mimeType": mime_type,
                    "data": base64.b64encode(reference_image).decode("ascii"),
                }
            }
        )
    parts.append({"text": prompt})

    contents: list[_ContentPayload] = [{"role": "user", "parts": parts}]
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


def _request_text_with_image(
    prompt: str,
    model: str,
    api_key: str,
    *,
    image_bytes: bytes,
    image_mime_type: str | None = None,
) -> tuple[str, _UsageMetadata | None]:
    """Request a text response from Gemini for an image + prompt."""
    generation_config: _GenerationConfig = {"responseModalities": ["TEXT"]}

    parts: list[_PartPayload] = [
        {
            "inlineData": {
                "mimeType": image_mime_type or "image/png",
                "data": base64.b64encode(image_bytes).decode("ascii"),
            }
        },
        {"text": prompt},
    ]

    contents: list[_ContentPayload] = [{"role": "user", "parts": parts}]
    payload: dict[str, object] = {"contents": contents, "generationConfig": generation_config}

    resp = requests.post(
        _API_URL.format(model=model),
        params={"key": api_key},
        json=payload,
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini text request failed: {resp.status_code} {resp.text}")

    data = cast(_GenerateContentResponse, resp.json())
    try:
        candidates = data.get("candidates")
        if not candidates:
            raise KeyError("candidates")
        parts_response = candidates[0]["content"]["parts"]
        text_value = None
        for part in parts_response:
            text_value = part.get("text")
            if text_value:
                break
        if not text_value:
            raise KeyError("text")
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected Gemini text response: {data}") from exc

    usage = data.get("usageMetadata")
    return text_value, usage


def _extract_description(text: str) -> str:
    """Extract a description field from JSON-like output."""
    stripped = _strip_code_fences(text)
    try:
        data_obj = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(data_obj, dict):
        data_obj = cast(dict[str, object], data_obj)
        desc = data_obj.get("description") or data_obj.get("canonical_description")
        if isinstance(desc, str) and desc.strip():
            return desc.strip()
    return stripped


def _describe_canonical_product(
    image_bytes: bytes,
    image_mime_type: str | None,
    project_root: Path,
    config: Config,
    api_key: str,
) -> str:
    """Describe the canonical product image using the prompt template."""
    template_path = project_root / "prompts" / "image_product_description.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Image description template not found at {template_path}")

    prompt_text = template_path.read_text(encoding="utf-8")
    text, usage = _request_text_with_image(
        prompt_text,
        config.gemini_image_model,
        api_key,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
    )
    _log_image_usage(usage, config, label="Gemini Image Description")
    return _extract_description(text)


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


def _is_placeholder_asset(path: Path) -> bool:
    """
    Determine whether an existing asset looks like one of our generated placeholders.

    This lets the image generator ignore placeholders when deciding whether to skip
    regeneration so real images are produced without forcing --overwrite.
    """
    ext = path.suffix.lower()
    try:
        if path.stat().st_size == 0:
            return True
    except OSError:
        return False
    expected_hash = _PLACEHOLDER_HASHES.get(ext)
    if expected_hash:
        try:
            return _hash_file(path) == expected_hash
        except OSError:
            return False
    # Fallback for unexpected suffixes: compare to bundled placeholder bytes.
    try:
        return path.read_bytes() == _placeholder_bytes(ext)
    except Exception:
        return False


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
        """Derive a usable alt description for a slot."""
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
    """Generate images for each slot in a site landing page."""
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

    def _slot_alt(slot: ImageSlot) -> str:
        """Derive a usable alt description for a slot."""
        alt_clean = slot.alt.strip() if slot.alt else ""
        if alt_clean:
            return alt_clean
        return Path(slot.src).stem.replace("-", " ").replace("_", " ")

    slots_payload: list[dict[str, str]] = []
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
            prompts_map[slot.src] = prompt_text
        slots_payload.append({"src": slot.src, "alt": _slot_alt(slot), "prompt": prompt_text})

    from . import gemini_runner  # Local import to avoid circular dependency.

    canonical_src, product_slots = gemini_runner.select_product_slots(
        slots_payload,
        product_prompt,
        project_root,
        config,
        debug=debug,
    )

    slot_order = [slot.src for slot in slots]
    if not product_slots:
        canonical_src = ""

    canonical_index = slot_order.index(canonical_src) if canonical_src else None
    canonical_reference: bytes | None = None
    canonical_mime_type: str | None = None
    canonical_description: str | None = None

    generated: list[Path] = []
    for idx, slot in enumerate(slots):
        target_path = site_dir / slot.src
        existing = target_path.exists() and not overwrite and not _is_placeholder_asset(target_path)
        if existing:
            if canonical_src == slot.src and canonical_reference is None:
                try:
                    canonical_reference = target_path.read_bytes()
                except OSError:
                    canonical_reference = None
                if canonical_reference is not None:
                    canonical_mime_type = _guess_image_mime_type(target_path)
                    canonical_description = _describe_canonical_product(
                        canonical_reference,
                        canonical_mime_type,
                        project_root,
                        config,
                        api_key,
                    )
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
            prompts_map[slot.src] = prompt_text

        should_use_reference = (
            canonical_reference is not None
            and canonical_index is not None
            and idx > canonical_index
            and slot.src in product_slots
        )

        if should_use_reference:
            prompt_text = _format_reference_prompt(prompt_text, canonical_description)
            image_bytes, usage = _request_image(
                prompt_text,
                config.gemini_image_model,
                api_key,
                reference_image=canonical_reference,
                reference_mime_type=canonical_mime_type,
            )
        else:
            image_bytes, usage = _request_image(prompt_text, config.gemini_image_model, api_key)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(image_bytes)
        _log_image_usage(usage, config)
        generated.append(target_path)

        if canonical_src == slot.src:
            canonical_reference = image_bytes
            canonical_mime_type = _guess_image_mime_type(target_path)
            canonical_description = _describe_canonical_product(
                canonical_reference,
                canonical_mime_type,
                project_root,
                config,
                api_key,
            )

    return generated
