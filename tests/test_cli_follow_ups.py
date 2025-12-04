from typer.testing import CliRunner

from landing_genie import cli
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
    monkeypatch.setattr(cli, "serve_local", lambda slug, project_root, debug=False: f"http://localhost/{slug}")

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
