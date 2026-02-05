"""Tests for image prompt generation and follow-ups."""

from pathlib import Path
from typing import Any, Optional

from landing_genie import gemini_runner
from landing_genie.config import Config


def _test_config() -> Config:
    """Build a test Config instance."""
    return Config(
        root_domain="example.com",
        cf_account_id="test-account",
        cf_api_token="test-token",
        gemini_code_model="gemini-2.5-pro",
        gemini_image_model="gemini-2.5-flash-image",
        gemini_cli_command="gemini",
        gemini_api_key=None,
        gemini_telemetry_otlp_endpoint=None,
        gemini_image_cost_per_1k_tokens=None,
    )


def test_suggest_image_follow_up_questions(tmp_path, monkeypatch) -> None:
    """Ensure image follow-up questions are parsed and logged."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "image_follow_up_questions_prompt.md").write_text(
        "Image follow-ups for {{ product_prompt }} (limit {{ max_follow_up_questions }})", encoding="utf-8"
    )

    stdout = '{"questions": ["What visual style should we use?", "Any brand colors to include?"]}'
    call_log: list[dict[str, Any]] = []

    def fake_run_gemini(
        prompt_text: str,
        model: str,
        config: Config,
        cwd: Optional[Path] = None,
        *,
        output_format: str = "json",
        capture_output: bool = False,
        debug: bool = False,
    ) -> str:
        """Capture follow-up prompt and return stub JSON."""
        call_log.append({"prompt": prompt_text, "output_format": output_format, "capture_output": capture_output})
        return stdout

    monkeypatch.setattr(gemini_runner, "_run_gemini", fake_run_gemini)

    config = _test_config()
    questions = gemini_runner.suggest_image_follow_up_questions(
        product_prompt="test product", project_root=tmp_path, config=config, debug=False
    )

    assert questions == ["What visual style should we use?", "Any brand colors to include?"]
    assert f"limit {gemini_runner.MAX_IMAGE_FOLLOW_UP_QUESTIONS}" in call_log[0]["prompt"]
    assert call_log[0]["capture_output"] is True
    assert call_log[0]["output_format"] == "json"


def test_generate_image_prompt_uses_template(tmp_path, monkeypatch) -> None:
    """Ensure image prompt template fields are filled."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "image_prompt.md").write_text(
        "Prompt for {{ slot_src }} {{ slot_alt }} {{ product_prompt }} "
        "{{ image_follow_up_context }} {{ image_visual_bible }}",
        encoding="utf-8",
    )

    call_log: list[str] = []

    def fake_run_gemini(
        prompt_text: str,
        model: str,
        config: Config,
        cwd: Optional[Path] = None,
        *,
        output_format: str = "json",
        capture_output: bool = False,
        debug: bool = False,
    ) -> str:
        """Capture prompt text and return stub image prompt."""
        call_log.append(prompt_text)
        return '{"prompt": "final image prompt"}'

    monkeypatch.setattr(gemini_runner, "_run_gemini", fake_run_gemini)

    config = _test_config()
    prompt = gemini_runner.generate_image_prompt(
        slot_src="assets/hero.jpg",
        slot_alt="Hero banner showing the product",
        product_prompt="AI tutor",
        project_root=tmp_path,
        config=config,
        follow_up_context="- Prefer bright colors",
        visual_bible='{"color_palette":"teal","material":"glass"}',
        debug=False,
    )

    assert prompt == "final image prompt"
    assert call_log, "generate_image_prompt did not invoke _run_gemini"
    sent_prompt = call_log[0]
    assert "assets/hero.jpg" in sent_prompt
    assert "Hero banner showing the product" in sent_prompt
    assert "AI tutor" in sent_prompt
    assert "Prefer bright colors" in sent_prompt
    assert '"color_palette":"teal"' in sent_prompt


def test_generate_image_visual_bible_uses_template(tmp_path, monkeypatch) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "image_visual_bible.md").write_text(
        "Bible for {{ product_prompt }} with {{ image_follow_up_context }}", encoding="utf-8"
    )

    call_log: list[str] = []

    def fake_run_gemini(
        prompt_text: str,
        model: str,
        config: Config,
        cwd: Optional[Path] = None,
        *,
        output_format: str = "json",
        capture_output: bool = False,
        debug: bool = False,
    ) -> str:
        call_log.append(prompt_text)
        return '{"color_palette":"navy","primary_material":"aluminum"}'

    monkeypatch.setattr(gemini_runner, "_run_gemini", fake_run_gemini)

    config = _test_config()
    bible = gemini_runner.generate_image_visual_bible(
        product_prompt="Smart bottle",
        project_root=tmp_path,
        config=config,
        follow_up_context="- Matte finish",
        debug=False,
    )

    assert bible == '{"color_palette":"navy","primary_material":"aluminum"}'
    assert call_log, "generate_image_visual_bible did not invoke _run_gemini"
    sent_prompt = call_log[0]
    assert "Smart bottle" in sent_prompt
    assert "Matte finish" in sent_prompt
