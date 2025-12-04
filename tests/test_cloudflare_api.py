from __future__ import annotations

from typing import Any, Dict

from pytest import MonkeyPatch

from landing_genie import cloudflare_api
from landing_genie.cloudflare_api import PRODUCTION_BRANCH, _ensure_pages_project  # pyright: ignore[reportPrivateUsage]
from landing_genie.config import Config


def _config() -> Config:
    return Config(
        root_domain="example.com",
        cf_account_id="account",
        cf_api_token="token",
        gemini_code_model="code-model",
        gemini_image_model="image-model",
        gemini_cli_command="gemini",
        gemini_api_key="api-key",
        gemini_telemetry_otlp_endpoint=None,
        gemini_image_cost_per_1k_tokens=None,
    )


def test_ensure_pages_project_skips_when_existing(monkeypatch: MonkeyPatch) -> None:
    calls: Dict[str, int] = {"post": 0, "get": 0}

    def fake_get(url: str, headers: Dict[str, str], timeout: int):
        calls["get"] += 1

        class Resp:
            status_code = 200
            ok = True
            text = "ok"

            @staticmethod
            def json() -> Dict[str, Any]:
                return {"success": True, "result": {"name": "proj"}}

        return Resp()

    def fake_request(method: str, path: str, config: Config, **kwargs: Any) -> Dict[str, Any]:
        calls["post"] += 1
        return {}

    monkeypatch.setattr(cloudflare_api.requests, "get", fake_get)
    monkeypatch.setattr(cloudflare_api, "_request", fake_request)

    _ensure_pages_project("proj", _config())

    assert calls["get"] == 1
    assert calls["post"] == 0


def test_ensure_pages_project_creates_when_missing(monkeypatch: MonkeyPatch) -> None:
    calls: Dict[str, Any] = {}

    def fake_get(url: str, headers: Dict[str, str], timeout: int):
        class Resp:
            status_code = 404
            ok = False
            text = "not found"

            @staticmethod
            def json() -> Dict[str, Any]:
                return {"success": False}

        return Resp()

    def fake_request(method: str, path: str, config: Config, **kwargs: Any) -> Dict[str, Any]:
        calls["method"] = method
        calls["path"] = path
        calls["json"] = kwargs.get("json")
        return {"success": True}

    monkeypatch.setattr(cloudflare_api.requests, "get", fake_get)
    monkeypatch.setattr(cloudflare_api, "_request", fake_request)

    _ensure_pages_project("proj", _config())

    assert calls["method"] == "POST"
    assert calls["path"].endswith("/pages/projects")
    assert calls["json"] == {
        "name": "proj",
        "production_branch": PRODUCTION_BRANCH,
    }
