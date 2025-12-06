from typer.testing import CliRunner

from types import SimpleNamespace

from landing_genie import cli, gemini_runner
from landing_genie.config import Config


def test_new_skips_followups_when_flag_disabled(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    dummy_config = Config(
        root_domain="example.com",
        cf_account_id="acc",
        cf_api_token="token",
        gemini_code_model="gemini-2.5-pro",
        gemini_image_model="gemini-2.5-flash-image",
        gemini_cli_command="gemini",
        gemini_api_key=None,
        gemini_telemetry_otlp_endpoint=None,
        gemini_image_cost_per_1k_tokens=None,
    )

    monkeypatch.setattr(cli.Config, "load", classmethod(lambda cls: dummy_config))
    monkeypatch.setattr(cli, "_project_root", lambda: tmp_path)

    def _fail_suggest(*_args, **_kwargs):
        raise AssertionError("follow-up questions should be skipped when disabled")

    monkeypatch.setattr(cli, "suggest_follow_up_questions", _fail_suggest)

    generated: list[dict[str, str]] = []
    site_dir = tmp_path / "sites" / "sluggy"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text("<html></html>")

    def _fake_generate_site(**kwargs):
        generated.append(kwargs)

    monkeypatch.setattr(cli, "generate_site", _fake_generate_site)
    monkeypatch.setattr(cli, "serve_local", lambda slug, project_root, config=None, debug=False: f"http://localhost/{slug}")

    result = runner.invoke(
        cli.app,
        [
            "new",
            "--prompt",
            "test prompt",
            "--suggested-subdomain",
            "sluggy",
            "--no-images",
            "--no-open-browser",
            "--no-follow-ups",
        ],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert generated, "generate_site was not called"


def test_new_generates_image_prompts_when_images_disabled(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    dummy_config = Config(
        root_domain="example.com",
        cf_account_id="acc",
        cf_api_token="token",
        gemini_code_model="gemini-2.5-flash",
        gemini_image_model="gemini-2.5-flash-image",
        gemini_cli_command="gemini",
        gemini_api_key=None,
        gemini_telemetry_otlp_endpoint=None,
        gemini_image_cost_per_1k_tokens=None,
    )

    monkeypatch.setattr(cli.Config, "load", classmethod(lambda cls: dummy_config))
    monkeypatch.setattr(cli, "_project_root", lambda: tmp_path)

    def _fail_generate_images(**_kwargs):
        raise AssertionError("image generation should be skipped when --no-images is set")

    prompts_called: list[dict] = []

    def _fake_generate_image_prompts(**kwargs):
        prompts_called.append(kwargs)
        return [("assets/hero.png", "prompt")]

    def _fake_generate_site(**kwargs):
        site_dir = tmp_path / "sites" / kwargs["slug"]
        site_dir.mkdir(parents=True, exist_ok=True)
        (site_dir / "index.html").write_text('<img src="assets/hero.png" alt="Hero">')

    monkeypatch.setattr(cli, "generate_images_for_site", _fail_generate_images)
    monkeypatch.setattr(cli, "generate_image_prompts_for_site", _fake_generate_image_prompts)
    monkeypatch.setattr(cli, "generate_site", _fake_generate_site)
    monkeypatch.setattr(cli, "ensure_placeholder_assets", lambda **_kwargs: [])
    monkeypatch.setattr(cli, "serve_local", lambda slug, project_root, config=None, debug=False: f"http://localhost/{slug}")

    result = runner.invoke(
        cli.app,
        [
            "new",
            "--prompt",
            "test prompt",
            "--suggested-subdomain",
            "sluggy",
            "--no-images",
            "--no-open-browser",
            "--no-follow-ups",
            "--no-image-follow-ups",
        ],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert prompts_called, "image prompts should be generated even when images are disabled"
    assert "Image prompts generated" in result.output


def test_new_logs_prompts_and_overwrites(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    dummy_config = Config(
        root_domain="example.com",
        cf_account_id="acc",
        cf_api_token="token",
        gemini_code_model="gemini-2.5-pro",
        gemini_image_model="gemini-2.5-flash-image",
        gemini_cli_command="gemini",
        gemini_api_key=None,
        gemini_telemetry_otlp_endpoint=None,
        gemini_image_cost_per_1k_tokens=None,
    )

    monkeypatch.setattr(cli.Config, "load", classmethod(lambda cls: dummy_config))
    monkeypatch.setattr(cli, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "ensure_placeholder_assets", lambda **_kwargs: [])
    monkeypatch.setattr(cli, "generate_images_for_site", lambda **_kwargs: [])
    monkeypatch.setattr(cli, "generate_image_prompts_for_site", lambda **_kwargs: [])
    monkeypatch.setattr(cli, "serve_local", lambda slug, project_root, config=None, debug=False: f"http://localhost/{slug}")

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "runtime_generation_prompt.md").write_text(
        "Landing prompt for {{ product_prompt }}",
        encoding="utf-8",
    )

    def _fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(gemini_runner.subprocess, "run", _fake_run)

    def _invoke(prompt_text: str) -> str:
        result = runner.invoke(
            cli.app,
            [
                "new",
                "--prompt",
                prompt_text,
                "--suggested-subdomain",
                "sluggy",
                "--no-images",
                "--no-open-browser",
                "--no-follow-ups",
                "--no-image-follow-ups",
            ],
            input="y\n",
        )
        assert result.exit_code == 0, result.output
        log_path = tmp_path / ".log" / "gemini_prompts.log"
        return log_path.read_text(encoding="utf-8")

    first_log = _invoke("first prompt")
    second_log = _invoke("second prompt")

    assert "first prompt" in first_log
    assert "second prompt" in second_log
    assert "first prompt" in second_log, "log should append across runs, not overwrite"


def test_prompt_log_respects_cap(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    dummy_config = Config(
        root_domain="example.com",
        cf_account_id="acc",
        cf_api_token="token",
        gemini_code_model="gemini-2.5-pro",
        gemini_image_model="gemini-2.5-flash-image",
        gemini_cli_command="gemini",
        gemini_api_key=None,
        gemini_telemetry_otlp_endpoint=None,
        gemini_image_cost_per_1k_tokens=None,
    )

    monkeypatch.setattr(cli.Config, "load", classmethod(lambda cls: dummy_config))
    monkeypatch.setattr(cli, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "ensure_placeholder_assets", lambda **_kwargs: [])
    monkeypatch.setattr(cli, "generate_images_for_site", lambda **_kwargs: [])
    monkeypatch.setattr(cli, "generate_image_prompts_for_site", lambda **_kwargs: [])
    monkeypatch.setattr(cli, "serve_local", lambda slug, project_root, config=None, debug=False: f"http://localhost/{slug}")
    monkeypatch.setenv("LANDING_GENIE_PROMPT_LOG_MAX_BYTES", "200")

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "runtime_generation_prompt.md").write_text(
        "Landing prompt for {{ product_prompt }}",
        encoding="utf-8",
    )

    def _fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(gemini_runner.subprocess, "run", _fake_run)

    for idx in range(3):
        text = f"prompt {idx} " + ("x" * 80)
        result = runner.invoke(
            cli.app,
            [
                "new",
                "--prompt",
                text,
                "--suggested-subdomain",
                f"sluggy-{idx}",
                "--no-images",
                "--no-open-browser",
                "--no-follow-ups",
                "--no-image-follow-ups",
            ],
            input="y\n",
        )
        assert result.exit_code == 0, result.output

    log_path = tmp_path / ".log" / "gemini_prompts.log"
    log_content = log_path.read_text(encoding="utf-8")

    assert log_path.stat().st_size <= 200
    assert "prompt 2" in log_content
    assert "prompt 0" not in log_content or "[truncated]" in log_content


def test_image_prompt_generation_logs_result(monkeypatch, tmp_path) -> None:
    dummy_config = Config(
        root_domain="example.com",
        cf_account_id="acc",
        cf_api_token="token",
        gemini_code_model="gemini-2.5-pro",
        gemini_image_model="gemini-2.5-flash-image",
        gemini_cli_command="gemini",
        gemini_api_key=None,
        gemini_telemetry_otlp_endpoint=None,
        gemini_image_cost_per_1k_tokens=None,
    )

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "image_prompt.md").write_text(
        "Image prompt {{ product_prompt }} {{ slot_src }} {{ slot_alt }} {{ image_follow_up_context }}",
        encoding="utf-8",
    )

    monkeypatch.setenv("LANDING_GENIE_PROMPT_LOG_PATH", str(tmp_path / ".log" / "gemini_prompts.log"))

    def _fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout='{"prompt": "generated image prompt"}', stderr="")

    monkeypatch.setattr(gemini_runner.subprocess, "run", _fake_run)

    result = gemini_runner.generate_image_prompt(
        slot_src="assets/hero.png",
        slot_alt="Hero shot",
        product_prompt="product",
        project_root=tmp_path,
        config=dummy_config,
    )

    assert result == "generated image prompt"
    log_path = tmp_path / ".log" / "gemini_prompts.log"
    content = log_path.read_text(encoding="utf-8")
    assert "image-prompt result" in content
    assert "assets/hero.png" in content
    assert "generated image prompt" in content
