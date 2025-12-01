from __future__ import annotations
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterator, Optional, cast

from .config import Config


def _iter_json_objects(text: str) -> Iterator[dict[str, Any]]:
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
    found_prompt: Optional[int] = None
    found_completion: Optional[int] = None
    found_total: Optional[int] = None

    def _int_or_none(value: Any) -> Optional[int]:
        return value if isinstance(value, int) else None

    for obj in _iter_json_objects(stdout):
        usage = obj.get("usageMetadata")
        if isinstance(usage, dict):
            usage_dict = cast(dict[str, Any], usage)
            return (
                _int_or_none(usage_dict.get("promptTokenCount")),
                _int_or_none(usage_dict.get("candidatesTokenCount")),
                _int_or_none(usage_dict.get("totalTokenCount")),
            )

        stats = obj.get("stats")
        model_stats: dict[str, Any] = {}
        if isinstance(stats, dict):
            stats_dict = cast(dict[str, Any], stats)
            models = stats_dict.get("models")
            if isinstance(models, dict):
                models_dict = cast(dict[str, Any], models)
                model_entry = models_dict.get(model)
                if isinstance(model_entry, dict):
                    model_stats = cast(dict[str, Any], model_entry)

        tokens: dict[str, Any] = {}
        tokens_entry = model_stats.get("tokens")
        if isinstance(tokens_entry, dict):
            tokens = cast(dict[str, Any], tokens_entry)
        if tokens:
            return (
                _int_or_none(tokens.get("input") or tokens.get("prompt")),
                _int_or_none(tokens.get("output") or tokens.get("completion")),
                _int_or_none(tokens.get("total")),
            )

        attrs = obj.get("attributes", {})
        if isinstance(attrs, dict):
            attrs_dict = cast(dict[str, Any], attrs)
            input_tokens = _int_or_none(attrs_dict.get("gen_ai.usage.input_tokens"))
            output_tokens = _int_or_none(attrs_dict.get("gen_ai.usage.output_tokens"))
        else:
            input_tokens = output_tokens = None
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

    prompt_tokens: Optional[int] = found_prompt or _m(r"promptTokenCount['\"]?\s*[:=]\s*(\d+)")
    completion_tokens: Optional[int] = found_completion or _m(r"(?:candidatesTokenCount|output_tokens)['\"]?\s*[:=]\s*(\d+)")
    total_tokens: Optional[int] = found_total or _m(r"totalTokenCount['\"]?\s*[:=]\s*(\d+)")

    if total_tokens is None:
        total_tokens = _m(r"tokens[^{}]*?total['\"]?\s*[:=]\s*(\d+)")
    if prompt_tokens is None:
        prompt_tokens = _m(r"tokens[^{}]*?(?:input|prompt)['\"]?\s*[:=]\s*(\d+)")
    if completion_tokens is None:
        completion_tokens = _m(r"tokens[^{}]*?(?:output|completion)['\"]?\s*[:=]\s*(\d+)")

    return prompt_tokens, completion_tokens, total_tokens


def _extract_candidate_texts(obj: dict[str, Any]) -> list[str]:
    texts: list[str] = []

    def _append_text(value: Any) -> None:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                texts.append(stripped)

    candidates = obj.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            _append_text(candidate.get("text"))

            content = candidate.get("content")
            if isinstance(content, dict):
                parts = content.get("parts")
                if isinstance(parts, list):
                    for part in parts:
                        if isinstance(part, dict):
                            _append_text(part.get("text"))
            _append_text(candidate.get("output_text"))

    _append_text(obj.get("text"))
    return texts


def _parse_questions_from_text(text: str) -> list[str]:
    questions: list[str] = []

    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None

    if isinstance(parsed, dict):
        raw = parsed.get("questions")
        if isinstance(raw, list):
            for q in raw:
                if isinstance(q, str):
                    q_clean = q.strip()
                    if q_clean:
                        questions.append(q_clean)
        if questions:
            return questions

    for line in text.splitlines():
        cleaned = line.strip().lstrip("-•0123456789.) ")
        if cleaned.endswith("?") and len(cleaned) > 6:
            questions.append(cleaned)
    return questions


def suggest_follow_up_questions(
    product_prompt: str,
    project_root: Path,
    config: Config,
    max_questions: int = 4,
    debug: bool = False,
) -> list[str]:
    """Ask Gemini CLI to propose clarifying questions for the landing prompt."""
    prompts_dir = project_root / "prompts"
    template_path = prompts_dir / "follow_up_questions_prompt.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Follow-up prompt template not found at {template_path}")

    template = template_path.read_text(encoding="utf-8")
    prompt_text = template.replace("{{ product_prompt }}", product_prompt)

    stdout = _run_gemini(
        prompt_text,
        config.gemini_code_model,
        config,
        output_format="json",
        capture_output=True,
        debug=debug,
    ) or ""

    found_questions: list[str] = []
    for obj in _iter_json_objects(stdout):
        if not isinstance(obj, dict):
            continue
        direct = obj.get("questions")
        if isinstance(direct, list):
            for q in direct:
                if isinstance(q, str):
                    q_clean = q.strip()
                    if q_clean:
                        found_questions.append(q_clean)

        for text in _extract_candidate_texts(obj):
            found_questions.extend(_parse_questions_from_text(text))

    if not found_questions:
        found_questions.extend(_parse_questions_from_text(stdout))

    def _keep(question: str) -> Optional[str]:
        cleaned = question.strip()
        if not cleaned:
            return None
        if cleaned.replace(".", "").strip() == "":
            return None
        if cleaned in {"...", ".."}:
            return None
        if len(cleaned) < 6:
            return None
        return cleaned

    deduped: list[str] = []
    seen: set[str] = set()
    for q in found_questions:
        cleaned = _keep(q)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        deduped.append(cleaned)
        seen.add(key)

    return deduped[:max_questions]


def _run_gemini(
    prompt_text: str,
    model: str,
    config: Config,
    cwd: Optional[Path] = None,
    *,
    output_format: str = "json",
    capture_output: bool = False,
    debug: bool = False,
) -> Optional[str]:
    debug_enabled = debug or bool(os.getenv("LANDING_GENIE_DEBUG"))
    if debug_enabled:
        print("[Gemini CLI debug] Prompt to be sent:\n" + prompt_text + "\n--- end prompt ---")
    cmd = [
        config.gemini_cli_command,
        "--model", model,
        "--prompt", prompt_text,
        "--yolo",
    ]
    if output_format:
        cmd.extend(["--output-format", output_format])
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

    return result.stdout if capture_output else None


def generate_site(
    slug: str,
    product_prompt: str,
    project_root: Path,
    config: Config,
    *,
    follow_up_context: Optional[str] = None,
    debug: bool = False,
) -> None:
    prompts_dir = project_root / "prompts"
    template_path = prompts_dir / "runtime_generation_prompt.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Prompt template not found at {template_path}")

    site_dir = project_root / "sites" / slug
    site_dir.mkdir(parents=True, exist_ok=True)

    template = template_path.read_text(encoding="utf-8")
    clarifications = follow_up_context or "None provided."
    text = (
        template
        .replace("{{ slug }}", slug)
        .replace("{{ root_domain }}", config.root_domain)
        .replace("{{ product_prompt }}", product_prompt)
        .replace("{{ product_type }}", "hybrid")
        .replace("{{ follow_up_context }}", clarifications)
    )

    _run_gemini(text, config.gemini_code_model, config, cwd=site_dir, debug=debug)


def refine_site(slug: str, feedback: str, project_root: Path, config: Config, *, debug: bool = False) -> None:
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

    _run_gemini(text, config.gemini_code_model, config, cwd=site_dir, debug=debug)
