import json
from pathlib import Path
from typing import Any, Optional

from landing_genie.config import Config
from landing_genie import gemini_runner


def _test_config() -> Config:
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


def test_parse_follow_up_questions_with_code_fence() -> None:
    response_block = """```json
{
  "questions": [
    "Who is the primary target audience for this tool? (e.g., law enforcement, emergency services, industrial workers)",
    "What makes this tool unique compared to other cuff-breaking methods? (e.g., speed, portability, safety)",
    "Is this a real product or a fictional concept?",
    "What is the primary call to action for the landing page? (e.g., Buy Now, Join Waitlist, Learn More)"
  ]
}
```"""
    stdout = json.dumps(
        {
            "response": response_block,
            "stats": {"models": {"gemini-2.5-pro": {"tokens": {"input": 123}}}},
        }
    )

    questions = gemini_runner._parse_follow_up_questions(stdout, debug=False)

    assert questions == [
        "Who is the primary target audience for this tool? (e.g., law enforcement, emergency services, industrial workers)",
        "What makes this tool unique compared to other cuff-breaking methods? (e.g., speed, portability, safety)",
        "Is this a real product or a fictional concept?",
        "What is the primary call to action for the landing page? (e.g., Buy Now, Join Waitlist, Learn More)",
    ]


def test_follow_up_questions_feed_generation_prompt(tmp_path, monkeypatch) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "follow_up_questions_prompt.md").write_text(
        "Follow-ups for {{ product_prompt }} (limit {{ max_follow_up_questions }})", encoding="utf-8"
    )
    (prompts_dir / "runtime_generation_prompt.md").write_text(
        "{{ follow_up_block }}", encoding="utf-8"
    )
    (prompts_dir / "snippets.md").write_text(
        "## follow_up_block\nFollow-up clarifications:\n{{ follow_up_context }}\n", encoding="utf-8"
    )

    response_block = """```json
{
  "questions": [
    "Who is the primary target audience for this tool?",
    "What is the primary call to action for the landing page?",
    "What proof or traction can we cite (users, results, partners)?",
    "What tone or brand cues should the page follow?",
    "Which sections matter most (hero, features, pricing, FAQ, contact)?"
  ]
}
```"""
    stdout = json.dumps({"response": response_block, "stats": {}})

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
        call_log.append(
            {
                "prompt": prompt_text,
                "capture_output": capture_output,
                "output_format": output_format,
                "cwd": cwd,
            }
        )
        if capture_output:
            assert output_format == "json"
            return stdout
        return ""

    monkeypatch.setattr(gemini_runner, "_run_gemini", fake_run_gemini)

    config = _test_config()
    questions = gemini_runner.suggest_follow_up_questions(
        product_prompt="cuff-breaking tool",
        project_root=tmp_path,
        config=config,
        debug=False,
    )

    assert questions == [
        "Who is the primary target audience for this tool?",
        "What is the primary call to action for the landing page?",
        "What proof or traction can we cite (users, results, partners)?",
        "What tone or brand cues should the page follow?",
        "Which sections matter most (hero, features, pricing, FAQ, contact)?",
    ]
    assert f"limit {gemini_runner.MAX_FOLLOW_UP_QUESTIONS}" in call_log[0]["prompt"]

    follow_up_context = "\n".join(f"- {q} Answer: provided" for q in questions)

    gemini_runner.generate_site(
        slug="cuffs",
        product_prompt="cuff-breaking tool",
        project_root=tmp_path,
        config=config,
        follow_up_context=follow_up_context,
        include_follow_up_context=True,
        debug=False,
    )

    assert len(call_log) == 2
    generation_prompt = call_log[-1]["prompt"]
    assert follow_up_context in generation_prompt
    assert "None provided." not in generation_prompt


def test_generate_site_excludes_followups_when_flag_false(tmp_path, monkeypatch) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "runtime_generation_prompt.md").write_text(
        "Header\n{{ follow_up_block }}\nFooter", encoding="utf-8"
    )
    (prompts_dir / "snippets.md").write_text(
        "## follow_up_block\nFollow-up clarifications:\n{{ follow_up_context }}\n", encoding="utf-8"
    )

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
        call_log.append({"prompt": prompt_text})
        return ""

    monkeypatch.setattr(gemini_runner, "_run_gemini", fake_run_gemini)

    config = _test_config()
    gemini_runner.generate_site(
        slug="sluggy",
        product_prompt="desc",
        project_root=tmp_path,
        config=config,
        follow_up_context=None,
        include_follow_up_context=False,
        debug=False,
    )

    assert call_log, "generate_site did not invoke _run_gemini"
    prompt_text = call_log[-1]["prompt"]
    assert "Follow-up clarifications" not in prompt_text
    assert "{{ follow_up_block }}" not in prompt_text
