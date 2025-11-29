from __future__ import annotations
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Iterator, Optional

from .config import Config


def _iter_json_objects(text: str) -> Iterator[dict]:
    """Yield JSON objects from a stream that may contain multiple blobs and noise."""
    decoder = json.JSONDecoder()
    idx = 0
    length = len(text)
    while idx < length:
        while idx < length and text[idx].isspace():
            idx += 1
        if idx >= length:
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        if isinstance(obj, dict):
            yield obj
        idx = end


def _extract_usage(stdout: str, model: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """
    Parse Gemini CLI stdout to find token counts.

    The CLI may emit multiple JSON objects and non-JSON lines. We scan JSON objects
    first, then fall back to regex against the raw text for inspected output that
    isn't valid JSON (e.g., single-quoted).
    """
    found_prompt = found_completion = found_total = None

    for obj in _iter_json_objects(stdout):
        usage = obj.get("usageMetadata")
        if usage:
            return (
                usage.get("promptTokenCount"),
                usage.get("candidatesTokenCount"),
                usage.get("totalTokenCount"),
            )

        stats = obj.get("stats", {})
        model_stats = stats.get("models", {}).get(model, {})
        tokens = model_stats.get("tokens", {})
        if tokens:
            return (
                tokens.get("input") or tokens.get("prompt"),
                tokens.get("output") or tokens.get("completion"),
                tokens.get("total"),
            )

        attrs = obj.get("attributes", {})
        input_tokens = attrs.get("gen_ai.usage.input_tokens")
        output_tokens = attrs.get("gen_ai.usage.output_tokens")
        if input_tokens is not None or output_tokens is not None:
            total_tokens = None
            if input_tokens is not None and output_tokens is not None:
                total_tokens = input_tokens + output_tokens
            found_prompt = found_prompt or input_tokens
            found_completion = found_completion or output_tokens
            found_total = found_total or total_tokens

    # Regex fallback for non-JSON telemetry output (single-quoted or inspected dicts).
    def _m(pattern: str) -> Optional[int]:
        match = re.search(pattern, stdout, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
        return int(match.group(1)) if match else None

    prompt_tokens = found_prompt or _m(r"promptTokenCount['\"]?\s*[:=]\s*(\d+)")
    completion_tokens = found_completion or _m(r"(?:candidatesTokenCount|output_tokens)['\"]?\s*[:=]\s*(\d+)")
    total_tokens = found_total or _m(r"totalTokenCount['\"]?\s*[:=]\s*(\d+)")

    if total_tokens is None:
        total_tokens = _m(r"tokens[^{}]*?total['\"]?\s*[:=]\s*(\d+)")
    if prompt_tokens is None:
        prompt_tokens = _m(r"tokens[^{}]*?(?:input|prompt)['\"]?\s*[:=]\s*(\d+)")
    if completion_tokens is None:
        completion_tokens = _m(r"tokens[^{}]*?(?:output|completion)['\"]?\s*[:=]\s*(\d+)")

    return prompt_tokens, completion_tokens, total_tokens


def _run_gemini(prompt_text: str, model: str, config: Config, cwd: Optional[Path] = None) -> None:
    cmd = [
        config.gemini_cli_command,
        "--model", model,
        "--prompt", prompt_text,
        "--yolo",
        "--output-format", "json",
    ]
    env = os.environ.copy()
    if config.gemini_api_key and not os.getenv("GEMINI_ALLOW_CLI_API_KEY"):
        # Avoid sending paid API keys to the CLI unless explicitly allowed.
        env.pop("GEMINI_API_KEY", None)
    if config.gemini_telemetry_otlp_endpoint:
        # Override the CLI's telemetry endpoint when running headless so OTLP export is enabled.
        env["GEMINI_TELEMETRY_OTLP_ENDPOINT"] = config.gemini_telemetry_otlp_endpoint
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Gemini CLI failed. Command: {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    # The CLI returns JSON; usageMetadata contains token counts when available.
    prompt_tokens, completion_tokens, total_tokens = _extract_usage(result.stdout, model)
    if any(v is not None for v in (prompt_tokens, completion_tokens, total_tokens)):
        print(
            f"[Gemini CLI] Tokens used (model={model}): "
            f"prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}"
        )


def generate_site(slug: str, product_prompt: str, project_root: Path, config: Config) -> None:
    prompts_dir = project_root / "prompts"
    template_path = prompts_dir / "runtime_generation_prompt.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Prompt template not found at {template_path}")

    site_dir = project_root / "sites" / slug
    site_dir.mkdir(parents=True, exist_ok=True)

    template = template_path.read_text(encoding="utf-8")
    text = (
        template
        .replace("{{ slug }}", slug)
        .replace("{{ root_domain }}", config.root_domain)
        .replace("{{ product_prompt }}", product_prompt)
        .replace("{{ product_type }}", "hybrid")
    )

    _run_gemini(text, config.gemini_code_model, config, cwd=site_dir)


def refine_site(slug: str, feedback: str, project_root: Path, config: Config) -> None:
    prompts_dir = project_root / "prompts"
    template_path = prompts_dir / "refine_landing_prompt.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Refine prompt template not found at {template_path}")

    site_dir = project_root / "sites" / slug
    if not site_dir.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    template = template_path.read_text(encoding="utf-8")
    text = (
        template
        .replace("{{ slug }}", slug)
        .replace("{{ feedback }}", feedback)
    )

    _run_gemini(text, config.gemini_code_model, config, cwd=site_dir)
