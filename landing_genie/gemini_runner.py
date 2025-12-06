from __future__ import annotations
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional, cast

from .config import Config
from .site_paths import normalize_site_dir


def _env_int(name: str, default: int, *, min_value: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
        return value if value >= min_value else default
    except ValueError:
        return default


MAX_FOLLOW_UP_QUESTIONS = _env_int("LANDING_GENIE_MAX_FOLLOW_UP_QUESTIONS", 20)
MAX_IMAGE_FOLLOW_UP_QUESTIONS = _env_int("LANDING_GENIE_MAX_IMAGE_FOLLOW_UP_QUESTIONS", 20)
PROMPT_LOG_ENV_VAR = "LANDING_GENIE_PROMPT_LOG_PATH"
PROMPT_LOG_MAX_BYTES_ENV_VAR = "LANDING_GENIE_PROMPT_LOG_MAX_BYTES"
PROMPT_LOG_MAX_MB_ENV_VAR = "LANDING_GENIE_PROMPT_LOG_MAX_MB"
DEFAULT_PROMPT_LOG_MAX_MB = 5
DEFAULT_PROMPT_LOG_MAX_BYTES = DEFAULT_PROMPT_LOG_MAX_MB * 1024 * 1024
DEFAULT_PROMPT_LOG_PATH = ".log/"


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


def _strip_code_fences(text: str) -> str:
    """
    Remove surrounding Markdown fences such as ```json ... ``` or ``` ... ```.
    """
    match = re.match(r"\s*```(?:json)?\s*(.*?)\s*```\s*$", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text.strip()


def _prompt_log_max_bytes() -> int:
    raw_mb = os.getenv(PROMPT_LOG_MAX_MB_ENV_VAR)
    if raw_mb:
        try:
            value_mb = float(raw_mb)
            value_bytes = int(value_mb * 1024 * 1024)
            if value_bytes > 0:
                return value_bytes
        except ValueError:
            pass

    raw_bytes = os.getenv(PROMPT_LOG_MAX_BYTES_ENV_VAR)
    if raw_bytes:
        try:
            value_bytes = int(raw_bytes)
            if value_bytes > 0:
                return value_bytes
        except ValueError:
            pass
    return DEFAULT_PROMPT_LOG_MAX_BYTES


def _prompt_log_path() -> Optional[Path]:
    env_raw = os.getenv(PROMPT_LOG_ENV_VAR)
    raw = env_raw if env_raw is not None else DEFAULT_PROMPT_LOG_PATH
    raw = raw.strip()
    if raw == "":
        return None
    path = Path(raw)
    if raw.endswith(("/", os.sep)) or path.is_dir():
        path = path / "gemini_prompts.log"
    return path


def _enforce_log_cap(log_path: Path, max_bytes: int) -> None:
    try:
        size = log_path.stat().st_size
    except OSError:
        return
    if size <= max_bytes:
        return
    try:
        with log_path.open("rb") as fh:
            if max_bytes <= 0:
                data = b""
            else:
                fh.seek(-max_bytes, os.SEEK_END)
                data = fh.read()
        note = b"[truncated]\n"
        if max_bytes > len(note):
            data = note + data[-(max_bytes - len(note)) :]
        else:
            data = data[-max_bytes:]
        with log_path.open("wb") as fh:
            fh.write(data)
    except Exception as exc:
        print(f"[Gemini CLI debug] Failed to enforce prompt log cap: {exc}")


def _append_prompt_log(entry: str) -> None:
    log_path = _prompt_log_path()
    if not log_path:
        return

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(entry)
        _enforce_log_cap(log_path, _prompt_log_max_bytes())
    except Exception as exc:
        print(f"[Gemini CLI debug] Failed to log prompt to {log_path}: {exc}")


def _log_prompt(prompt_text: str, model: str) -> None:
    """Append the prompt being sent to Gemini CLI to a log file if configured."""
    log_path = _prompt_log_path()
    if not log_path:
        return

    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        divider = "=" * 72
        entry = (
            f"{divider}\n"
            f"{timestamp} | model={model}\n"
            f"{prompt_text}\n\n"
        )
        _append_prompt_log(entry)
    except Exception as exc:
        print(f"[Gemini CLI debug] Failed to log prompt to {log_path}: {exc}")


def _log_image_prompt_result(slot_src: str, prompt_text: str) -> None:
    log_path = _prompt_log_path()
    if not log_path or not prompt_text:
        return
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        divider = "-" * 72
        entry = (
            f"{divider}\n"
            f"{timestamp} | image-prompt result | slot={slot_src}\n"
            f"{prompt_text}\n\n"
        )
        _append_prompt_log(entry)
    except Exception as exc:
        print(f"[Gemini CLI debug] Failed to log image prompt result: {exc}")


def _parse_image_prompt_batch_response(stdout: str, *, debug: bool = False) -> dict[str, str]:
    debug_enabled = debug or bool(os.getenv("LANDING_GENIE_DEBUG"))

    def _debug(msg: str) -> None:
        if debug_enabled:
            print(msg)

    truncated = stdout if len(stdout) <= 4000 else stdout[:4000] + "...[truncated]"

    def _extract_from_text(text: str) -> dict[str, str]:
        try:
            data_obj = json.loads(text)
        except json.JSONDecodeError:
            data_obj = None
        if isinstance(data_obj, dict):
            data_dict = cast(dict[str, Any], data_obj)
            prompts_field = data_dict.get("prompts")
            prompts = cast(list[object] | None, prompts_field) if isinstance(prompts_field, list) else None
            results: dict[str, str] = {}
            if prompts:
                for item in prompts:
                    if not isinstance(item, dict):
                        continue
                    item_dict = cast(dict[str, Any], item)
                    src_raw = cast(str | None, item_dict.get("src"))
                    prompt_raw = cast(
                        str | None,
                        item_dict.get("prompt")
                        or item_dict.get("image_prompt")
                        or item_dict.get("imagePrompt"),
                    )
                    src = src_raw.strip() if isinstance(src_raw, str) else ""
                    prompt = prompt_raw.strip() if isinstance(prompt_raw, str) else ""
                    if src and prompt:
                        results[src] = prompt
            if results:
                return results
            response_field = data_dict.get("response")
            if isinstance(response_field, str):
                nested = _extract_from_text(response_field)
                if nested:
                    return nested
        stripped = _strip_code_fences(text)
        if stripped != text:
            nested = _extract_from_text(stripped)
            if nested:
                return nested
        return {}

    results = _extract_from_text(stdout)
    if not results:
        _debug(f"[Gemini CLI debug] Could not parse batch image prompts from stdout:\n{truncated}")
    return results


def _extract_questions_from_obj(obj: Mapping[str, Any]) -> list[str]:
    questions: list[str] = []
    raw = obj.get("questions")
    if isinstance(raw, list):
        for q in cast(list[object], raw):
            if isinstance(q, str):
                q_clean = q.strip()
                if q_clean:
                    questions.append(q_clean)
    return questions


def _parse_questions_from_text(text: str) -> list[str]:
    questions: list[str] = []

    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None

    if isinstance(parsed, dict):
        parsed_dict = cast(dict[str, Any], parsed)
        raw = parsed_dict.get("questions")
        if isinstance(raw, list):
            for q in cast(list[object], raw):
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


def _parse_follow_up_questions(stdout: str, *, debug: bool = False) -> list[str]:
    debug_enabled = debug or bool(os.getenv("LANDING_GENIE_DEBUG"))

    def _debug(msg: str) -> None:
        if debug_enabled:
            print(msg)

    truncated_stdout = stdout if len(stdout) <= 4000 else stdout[:4000] + "...[truncated]"
    _debug(f"[Gemini CLI debug] Raw follow-up stdout ({len(stdout)} chars):\n{truncated_stdout}")

    try:
        outer_raw = json.loads(stdout)
    except json.JSONDecodeError as exc:
        _debug("[Gemini CLI debug] Failed to parse follow-up stdout as JSON; see raw stdout above.")
        raise ValueError("Gemini follow-up questions response was not valid JSON") from exc

    if not isinstance(outer_raw, dict):
        _debug(f"[Gemini CLI debug] Follow-up stdout JSON was not an object: {type(outer_raw).__name__}")
        raise ValueError("Gemini follow-up questions response must be a JSON object")

    outer: dict[str, Any] = cast(dict[str, Any], outer_raw)

    direct_questions = _extract_questions_from_obj(outer)
    if direct_questions:
        return direct_questions

    response_field = outer.get("response")
    response_text = response_field if isinstance(response_field, str) else None
    if response_text is None:
        _debug("[Gemini CLI debug] Follow-up response missing or not a string; falling back to text parsing.")
        return _parse_questions_from_text(stdout)

    stripped = _strip_code_fences(response_text)
    if stripped != response_text:
        _debug("[Gemini CLI debug] Stripped Markdown code fences from follow-up response.")

    truncated_response = stripped if len(stripped) <= 4000 else stripped[:4000] + "...[truncated]"

    try:
        inner_raw = json.loads(stripped)
    except json.JSONDecodeError as exc:
        _debug(
            "[Gemini CLI debug] Follow-up response was not valid JSON; "
            f"raw response:\n{truncated_response}"
        )
        return _parse_questions_from_text(stripped)

    if not isinstance(inner_raw, dict):
        _debug("[Gemini CLI debug] Parsed follow-up response was not a JSON object; using text fallback.")
        return _parse_questions_from_text(stripped)

    inner = cast(dict[str, Any], inner_raw)

    inner_questions = _extract_questions_from_obj(inner)
    if inner_questions:
        return inner_questions

    _debug("[Gemini CLI debug] No questions array found after parsing response JSON; using text fallback.")
    return _parse_questions_from_text(stripped)


def _dedupe_questions(questions: list[str], max_questions: int) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()

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

    for q in questions:
        cleaned = _keep(q)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        deduped.append(cleaned)
        seen.add(key)
        if len(deduped) >= max_questions:
            break

    return deduped


def _parse_image_prompt_response(stdout: str, *, debug: bool = False) -> Optional[str]:
    debug_enabled = debug or bool(os.getenv("LANDING_GENIE_DEBUG"))

    def _debug(msg: str) -> None:
        if debug_enabled:
            print(msg)

    truncated = stdout if len(stdout) <= 4000 else stdout[:4000] + "...[truncated]"

    def _extract_from_text(text: str) -> Optional[str]:
        try:
            data_obj = json.loads(text)
        except json.JSONDecodeError:
            data_obj = None

        if isinstance(data_obj, dict):
            data_dict = cast(dict[str, Any], data_obj)
            for key in ("prompt", "image_prompt", "imagePrompt"):
                val = data_dict.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
            response_field = data_dict.get("response")
            if isinstance(response_field, str):
                nested = _extract_from_text(response_field)
                if nested:
                    return nested

        stripped = _strip_code_fences(text)
        if stripped != text:
            nested = _extract_from_text(stripped)
            if nested:
                return nested

        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        return lines[0] if lines else None

    prompt = _extract_from_text(stdout)
    if prompt:
        return prompt

    _debug(f"[Gemini CLI debug] Could not parse image prompt from stdout:\n{truncated}")
    return None


def _load_prompt_snippets(project_root: Path) -> dict[str, str]:
    """
    Load optional prompt snippets from prompts/snippets.md, split by `## name` headers.
    """
    snippets_path = project_root / "prompts" / "snippets.md"
    if not snippets_path.exists():
        return {}
    content = snippets_path.read_text(encoding="utf-8")
    pattern = re.compile(r"^##\s+([A-Za-z0-9_\-]+)\s*$", flags=re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return {}

    snippets: dict[str, str] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        raw_block = content[start:end].lstrip("\n")
        # Preserve trailing newline to keep blocks separated when inserted.
        snippets[match.group(1)] = raw_block.rstrip() + "\n"
    return snippets


def suggest_follow_up_questions(
    product_prompt: str,
    project_root: Path,
    config: Config,
    max_questions: int = MAX_FOLLOW_UP_QUESTIONS,
    debug: bool = False,
) -> list[str]:
    """Ask Gemini CLI to propose clarifying questions for the landing prompt."""
    debug_enabled = debug or bool(os.getenv("LANDING_GENIE_DEBUG"))
    prompts_dir = project_root / "prompts"
    template_path = prompts_dir / "follow_up_questions_prompt.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Follow-up prompt template not found at {template_path}")

    template = template_path.read_text(encoding="utf-8")
    prompt_text = (
        template
        .replace("{{ product_prompt }}", product_prompt)
        .replace("{{ max_follow_up_questions }}", str(MAX_FOLLOW_UP_QUESTIONS))
    )

    stdout = _run_gemini(
        prompt_text,
        config.gemini_code_model,
        config,
        output_format="json",
        capture_output=True,
        debug=debug,
    ) or ""

    parsed_questions = _parse_follow_up_questions(stdout, debug=debug)
    deduped = _dedupe_questions(parsed_questions, max_questions)

    if debug_enabled:
        if deduped:
            print(f"[Gemini CLI debug] Extracted follow-up questions: {deduped}")
        else:
            print("[Gemini CLI debug] No follow-up questions extracted; continuing without them.")

    return deduped


def suggest_image_follow_up_questions(
    product_prompt: str,
    project_root: Path,
    config: Config,
    max_questions: int = MAX_IMAGE_FOLLOW_UP_QUESTIONS,
    debug: bool = False,
) -> list[str]:
    """Ask Gemini CLI for clarifications specific to image generation."""
    prompts_dir = project_root / "prompts"
    template_path = prompts_dir / "image_follow_up_questions_prompt.md"
    if not template_path.exists():
        return []

    template = template_path.read_text(encoding="utf-8")
    prompt_text = (
        template
        .replace("{{ product_prompt }}", product_prompt)
        .replace("{{ max_follow_up_questions }}", str(MAX_IMAGE_FOLLOW_UP_QUESTIONS))
    )

    stdout = _run_gemini(
        prompt_text,
        config.gemini_code_model,
        config,
        output_format="json",
        capture_output=True,
        debug=debug,
    ) or ""

    parsed_questions = _parse_follow_up_questions(stdout, debug=debug)
    return _dedupe_questions(parsed_questions, max_questions)


def generate_image_prompt(
    slot_src: str,
    slot_alt: str,
    product_prompt: str,
    project_root: Path,
    config: Config,
    *,
    follow_up_context: Optional[str] = None,
    debug: bool = False,
) -> str:
    """Ask Gemini CLI to craft a rich prompt for a specific image slot."""
    prompts_dir = project_root / "prompts"
    template_path = prompts_dir / "image_prompt.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Image prompt template not found at {template_path}")

    clarifications = (follow_up_context or "None provided.").strip() or "None provided."
    slot_alt_clean = slot_alt.strip() if slot_alt else ""
    if not slot_alt_clean:
        # Derive a human-friendly hint from the filename if no alt text exists.
        slot_alt_clean = Path(slot_src).stem.replace("-", " ").replace("_", " ")

    template = template_path.read_text(encoding="utf-8")
    prompt_text = (
        template
        .replace("{{ product_prompt }}", product_prompt)
        .replace("{{ slot_src }}", slot_src)
        .replace("{{ slot_alt }}", slot_alt_clean or "image for the landing page")
        .replace("{{ image_follow_up_context }}", clarifications)
    )

    stdout = _run_gemini(
        prompt_text,
        config.gemini_code_model,
        config,
        output_format="json",
        capture_output=True,
        debug=debug,
    ) or ""

    prompt_result = _parse_image_prompt_response(stdout, debug=debug)
    if not prompt_result:
        truncated = stdout if len(stdout) <= 1000 else stdout[:1000] + "...[truncated]"
        raise RuntimeError(
            f"Gemini image prompt response could not be parsed for slot {slot_src}; stdout sample:\n{truncated}"
        )
    _log_image_prompt_result(slot_src, prompt_result)
    return prompt_result


def generate_image_prompts_batch(
    slots: list[dict[str, str]],
    product_prompt: str,
    project_root: Path,
    config: Config,
    *,
    follow_up_context: Optional[str] = None,
    debug: bool = False,
) -> dict[str, str]:
    """
    Ask Gemini CLI once to craft prompts for all image slots.
    Expected stdout: {"prompts":[{"src":"assets/hero.png","prompt":"..."}]}
    Returns mapping of src -> prompt text.
    """
    prompts_dir = project_root / "prompts"
    template_path = prompts_dir / "image_prompts_batch.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Batch image prompt template not found at {template_path}")

    clarifications = (follow_up_context or "None provided.").strip() or "None provided."
    slot_lines = "\n".join(
        f"- src: {slot.get('src','').strip()}\n  alt: {(slot.get('alt') or '').strip()}"
        for slot in slots
        if slot.get("src")
    )

    template = template_path.read_text(encoding="utf-8")
    prompt_text = (
        template
        .replace("{{ product_prompt }}", product_prompt)
        .replace("{{ image_follow_up_context }}", clarifications)
        .replace("{{ slot_list }}", slot_lines)
    )

    stdout = _run_gemini(
        prompt_text,
        config.gemini_code_model,
        config,
        output_format="json",
        capture_output=True,
        debug=debug,
    ) or ""

    prompts_map = _parse_image_prompt_batch_response(stdout, debug=debug)
    if not prompts_map:
        truncated = stdout if len(stdout) <= 1000 else stdout[:1000] + "...[truncated]"
        raise RuntimeError(
            "Gemini batch image prompt response could not be parsed; no prompts returned. "
            f"Stdout sample:\n{truncated}"
        )
    for src, prompt in prompts_map.items():
        _log_image_prompt_result(src, prompt)
    return prompts_map


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
    _log_prompt(prompt_text, model)
    if debug_enabled:
        print("[Gemini CLI debug] Prompt to be sent:\n" + prompt_text + "\n--- end prompt ---")
    cmd = [
        config.gemini_cli_command,
        "--model", model,
        "--yolo",
    ]
    if output_format:
        cmd.extend(["--output-format", output_format])
    cmd.append(prompt_text)
    env = os.environ.copy()
    # Respect README guidance: keep CLI text calls on the CLI's own auth unless explicitly allowed.
    allow_cli_api_key = os.getenv("GEMINI_ALLOW_CLI_API_KEY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if config.gemini_api_key and allow_cli_api_key:
        env["GEMINI_API_KEY"] = config.gemini_api_key
    else:
        env.pop("GEMINI_API_KEY", None)
    if config.gemini_telemetry_otlp_endpoint:
        # Override the CLI's telemetry endpoint when running headless so OTLP export is enabled.
        env["GEMINI_TELEMETRY_OTLP_ENDPOINT"] = config.gemini_telemetry_otlp_endpoint
    start_time = time.monotonic()
    stop_event = threading.Event()
    last_msg_len = 0

    def _print_status(status: str, elapsed: float) -> None:
        nonlocal last_msg_len
        line = f"[Gemini CLI] {status} {elapsed:.1f} s"
        padding = max(0, last_msg_len - len(line))
        print(f"\r{line}{' ' * padding}", end="", flush=True)
        last_msg_len = len(line)

    def _tick() -> None:
        while not stop_event.wait(0.2):
            _print_status("Running...", time.monotonic() - start_time)

    _print_status("Running...", 0.0)
    progress_thread = threading.Thread(target=_tick, daemon=True)
    progress_thread.start()

    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            capture_output=True,
            text=True,
        )
        elapsed = time.monotonic() - start_time
    except Exception:
        elapsed = time.monotonic() - start_time
        stop_event.set()
        progress_thread.join(timeout=0.5)
        _print_status("Failed after", elapsed)
        print()
        raise

    stop_event.set()
    progress_thread.join(timeout=0.5)
    _print_status("Completed in", elapsed)
    print()

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
    include_follow_up_context: bool = True,
    debug: bool = False,
) -> None:
    prompts_dir = project_root / "prompts"
    template_path = prompts_dir / "runtime_generation_prompt.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Prompt template not found at {template_path}")

    site_dir = project_root / "sites" / slug
    site_dir.mkdir(parents=True, exist_ok=True)

    template = template_path.read_text(encoding="utf-8")
    debug_enabled = debug or bool(os.getenv("LANDING_GENIE_DEBUG"))
    clarifications = follow_up_context or "None provided."
    snippets = _load_prompt_snippets(project_root)
    snippet_template = snippets.get("follow_up_block")
    default_follow_up_block = "- Follow-up clarifications:\n{{ follow_up_context }}\n\n"
    follow_up_block = ""
    if include_follow_up_context:
        block_template = snippet_template or default_follow_up_block
        follow_up_block = block_template.replace("{{ follow_up_context }}", clarifications)
    if debug_enabled:
        if follow_up_context:
            print(f"[Gemini CLI debug] Using follow-up clarifications:\n{follow_up_context}")
        else:
            print("[Gemini CLI debug] No follow-up clarifications provided; using 'None provided.'")
    text = (
        template
        .replace("{{ slug }}", slug)
        .replace("{{ root_domain }}", config.root_domain)
        .replace("{{ product_prompt }}", product_prompt)
        .replace("{{ product_type }}", "hybrid")
        .replace("{{ follow_up_context }}", clarifications)
        .replace("{{ follow_up_block }}", follow_up_block)
    )

    _run_gemini(text, config.gemini_code_model, config, cwd=site_dir, debug=debug)
    normalize_site_dir(slug, project_root)


def refine_site(slug: str, feedback: str, project_root: Path, config: Config, *, debug: bool = False) -> None:
    prompts_dir = project_root / "prompts"
    template_path = prompts_dir / "refine_landing_prompt.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Refine prompt template not found at {template_path}")

    site_dir = normalize_site_dir(slug, project_root)
    if not site_dir.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    template = template_path.read_text(encoding="utf-8")
    text = (
        template
        .replace("{{ slug }}", slug)
        .replace("{{ feedback }}", feedback)
    )

    _run_gemini(text, config.gemini_code_model, config, cwd=site_dir, debug=debug)
