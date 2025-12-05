import json
import time
from urllib import request
from urllib.parse import urlparse

from landing_genie import preview
from landing_genie.config import Config


def _dummy_config() -> Config:
    return Config(
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


def test_inject_preview_layer_inserts_script() -> None:
    html = "<html><body><h1>Hello</h1></body></html>"
    injected = preview._inject_preview_layer(html)
    assert "landing-genie-preview-script" in injected
    body_close = injected.lower().rfind("</body>")
    script_idx = injected.find("landing-genie-preview-script")
    assert script_idx != -1 and script_idx < body_close


def test_refine_endpoint_invokes_refine_site(monkeypatch, tmp_path) -> None:
    site_dir = tmp_path / "sites" / "demo"
    site_dir.mkdir(parents=True)
    (site_dir / "index.html").write_text("<html><body><section>Demo</section></body></html>")

    calls: dict[str, object] = {}

    def fake_refine_site(slug, feedback, project_root, config, debug=False):
        calls["slug"] = slug
        calls["feedback"] = feedback
        calls["project_root"] = project_root
        calls["config"] = config

    placeholder_calls: list[tuple[str, object]] = []

    def fake_placeholders(slug, project_root):
        placeholder_calls.append((slug, project_root))
        return []

    monkeypatch.setattr(preview, "refine_site", fake_refine_site)
    monkeypatch.setattr(preview, "ensure_placeholder_assets", fake_placeholders)

    config = _dummy_config()
    url = preview.serve_local("demo", tmp_path, config=config, port=0, debug=False)
    parsed = urlparse(url)
    port = parsed.port
    assert port is not None

    payload = json.dumps(
        {"instruction": "make it better", "sectionText": "Old copy", "sectionLabel": "Hero"}
    ).encode("utf-8")
    req = request.Request(
        f"http://localhost:{port}/__preview/refine",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    time.sleep(0.05)
    try:
        with request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
    finally:
        preview._stop_server(port)

    assert data["status"] == "ok"
    assert calls["slug"] == "demo"
    assert "make it better" in str(calls["feedback"])
    assert ("demo", tmp_path) in placeholder_calls
    assert isinstance(calls["config"], Config)
