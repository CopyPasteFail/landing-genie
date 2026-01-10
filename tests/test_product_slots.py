"""Tests for product slot selection and image references."""

import json
import shutil
from pathlib import Path
from typing import Any, Optional, TypeGuard, cast

import pytest

from landing_genie import gemini_runner
from landing_genie.config import Config
from landing_genie.image_generator import generate_images_for_site


def _test_config() -> Config:
    """Build a test Config instance."""
    return Config(
        root_domain="example.com",
        cf_account_id="test-account",
        cf_api_token="test-token",
        gemini_code_model="gemini-2.5-pro",
        gemini_image_model="gemini-2.5-flash-image",
        gemini_cli_command="gemini",
        gemini_api_key="test-key",
        gemini_telemetry_otlp_endpoint=None,
        gemini_image_cost_per_1k_tokens=None,
        gemini_image_input_cost_per_1k_tokens=None,
    )


def _write_prompt_template(tmp_path: Path) -> None:
    """Write a minimal product slots prompt template."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "image_product_slots_prompt.md").write_text(
        "Product: {{ product_prompt }}\n{{ slot_list }}",
        encoding="utf-8",
    )


def _write_site(tmp_path: Path) -> str:
    """Create a sample site with image slots and return its slug."""
    slug = "product-slots"
    site_dir = tmp_path / "sites" / slug
    assets_dir = site_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text(
        (
            '<img src="assets/hero.png" alt="Hero product">\n'
            '<img src="assets/mid.png" alt="Mid banner">\n'
            '<img src="assets/feature.png" alt="Feature product">\n'
        ),
        encoding="utf-8",
    )
    return slug


def _stub_prompts_batch(
    slots: list[dict[str, str]],
    *args: Any,
    **kwargs: Any,
) -> dict[str, str]:
    """Return a stubbed prompt map for slots."""
    return {slot["src"]: f"prompt {slot['src']}" for slot in slots}


def _is_list_of_str(value: object) -> TypeGuard[list[str]]:
    """Type guard for list[str]."""
    if not isinstance(value, list):
        return False
    value_list = cast(list[object], value)
    return all(isinstance(item, str) for item in value_list)


def _is_dict_of_str(value: object) -> TypeGuard[dict[str, str]]:
    """Type guard for dict[str, str]."""
    if not isinstance(value, dict):
        return False
    value_dict = cast(dict[object, object], value)
    return all(
        isinstance(key, str) and isinstance(val, str) for key, val in value_dict.items()
    )


def test_product_slots_empty_selection_generates_freely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure no reference image is used when slots are empty."""
    _write_prompt_template(tmp_path)
    slug = _write_site(tmp_path)

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
        """Stub Gemini to return an empty slots selection."""
        return '{"canonical_src":"","product_slots":[]}'

    monkeypatch.setattr(gemini_runner, "_run_gemini", fake_run_gemini)
    monkeypatch.setattr(gemini_runner, "generate_image_prompts_batch", _stub_prompts_batch)

    describe_calls: list[bytes] = []
    request_log: list[dict[str, Any]] = []

    def fake_describe(*args: Any, **kwargs: Any) -> str:
        """Stub description for canonical product."""
        describe_calls.append(b"called")
        return "desc"

    def fake_request_image(
        prompt: str,
        model: str,
        api_key: str,
        *,
        reference_image: bytes | None = None,
        reference_mime_type: str | None = None,
    ) -> tuple[bytes, None]:
        """Stub image generation while recording references."""
        request_log.append({"prompt": prompt, "reference": reference_image})
        return b"img", None

    monkeypatch.setattr("landing_genie.image_generator._describe_canonical_product", fake_describe)
    monkeypatch.setattr("landing_genie.image_generator._request_image", fake_request_image)

    generated = generate_images_for_site(
        slug=slug,
        product_prompt="test product",
        project_root=tmp_path,
        config=_test_config(),
        overwrite=True,
    )

    assert len(generated) == 3
    assert describe_calls == []
    assert all(entry["reference"] is None for entry in request_log)
    assert all("Canonical product description" not in entry["prompt"] for entry in request_log)


def test_product_slots_valid_selection_uses_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure canonical reference is used for selected slots."""
    _write_prompt_template(tmp_path)
    slug = _write_site(tmp_path)

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
        """Stub Gemini to select canonical and product slots."""
        return (
            '{"canonical_src":"assets/hero.png","product_slots":'
            '["assets/hero.png","assets/feature.png"]}'
        )

    monkeypatch.setattr(gemini_runner, "_run_gemini", fake_run_gemini)
    monkeypatch.setattr(gemini_runner, "generate_image_prompts_batch", _stub_prompts_batch)

    describe_calls: list[bytes] = []
    request_log: list[dict[str, Any]] = []

    def fake_describe(*args: Any, **kwargs: Any) -> str:
        """Stub description for canonical product."""
        describe_calls.append(b"called")
        return "desc"

    def fake_request_image(
        prompt: str,
        model: str,
        api_key: str,
        *,
        reference_image: bytes | None = None,
        reference_mime_type: str | None = None,
    ) -> tuple[bytes, None]:
        """Stub image generation while recording references."""
        request_log.append({"prompt": prompt, "reference": reference_image})
        return b"img", None

    monkeypatch.setattr("landing_genie.image_generator._describe_canonical_product", fake_describe)
    monkeypatch.setattr("landing_genie.image_generator._request_image", fake_request_image)

    generated = generate_images_for_site(
        slug=slug,
        product_prompt="test product",
        project_root=tmp_path,
        config=_test_config(),
        overwrite=True,
    )

    assert len(generated) == 3
    assert describe_calls == [b"called"]
    assert "assets/hero.png" in request_log[0]["prompt"]

    with_reference = [entry for entry in request_log if entry["reference"] is not None]
    assert len(with_reference) == 1
    assert "assets/feature.png" in with_reference[0]["prompt"]
    assert "Canonical product description: desc" in with_reference[0]["prompt"]

    without_reference = [entry for entry in request_log if entry["reference"] is None]
    assert len(without_reference) == 2
    assert all("Canonical product description" not in entry["prompt"] for entry in without_reference)


def test_select_product_slots_invalid_json_returns_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure invalid JSON from Gemini yields empty selection."""
    _write_prompt_template(tmp_path)
    slots: list[dict[str, str]] = [
        {"src": "assets/hero.png", "alt": "Hero", "prompt": "Hero product"},
        {"src": "assets/feature.png", "alt": "Feature", "prompt": "Feature product"},
    ]

    def fake_run_gemini(*args: Any, **kwargs: Any) -> str:
        """Return invalid JSON to trigger empty selection."""
        return "not json"

    monkeypatch.setattr(gemini_runner, "_run_gemini", fake_run_gemini)

    canonical_src, product_slots = gemini_runner.select_product_slots(
        slots,
        "test product",
        tmp_path,
        _test_config(),
        debug=False,
    )

    assert canonical_src == ""
    assert product_slots == []


def test_select_product_slots_invalid_canonical_returns_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure invalid canonical slot selection yields empty output."""
    _write_prompt_template(tmp_path)
    slots: list[dict[str, str]] = [
        {"src": "assets/hero.png", "alt": "Hero", "prompt": "Hero product"},
        {"src": "assets/feature.png", "alt": "Feature", "prompt": "Feature product"},
    ]

    def fake_run_gemini(*args: Any, **kwargs: Any) -> str:
        """Return selection with canonical mismatch."""
        return '{"canonical_src":"assets/hero.png","product_slots":["assets/feature.png"]}'

    monkeypatch.setattr(gemini_runner, "_run_gemini", fake_run_gemini)

    canonical_src, product_slots = gemini_runner.select_product_slots(
        slots,
        "test product",
        tmp_path,
        _test_config(),
        debug=False,
    )

    assert canonical_src == ""
    assert product_slots == []


def test_product_slots_report_only(capsys: pytest.CaptureFixture[str]) -> None:
    """Print accuracy report for product slot selection fixtures."""
    config = _test_config()
    if not shutil.which(config.gemini_cli_command):
        return

    project_root = Path(__file__).resolve().parents[1]
    fixture_path = project_root / "tests" / "fixtures" / "product_slots_inputs.json"
    data: list[dict[str, Any]] = json.loads(fixture_path.read_text(encoding="utf-8"))

    total_cases = 0
    total_score = 0.0
    for idx, case in enumerate(data, start=1):
        expected_raw = case.get("expected_product_slots")
        if not isinstance(expected_raw, list):
            with capsys.disabled():
                print(f"[product-slots] case {idx}: missing expected_product_slots; skipping")
            continue
        expected_raw_list = cast(list[object], expected_raw)
        if not _is_list_of_str(expected_raw_list):
            with capsys.disabled():
                print(f"[product-slots] case {idx}: invalid expected_product_slots; skipping")
            continue
        expected_slots = expected_raw_list

        slots_raw = case.get("slots", [])
        if not isinstance(slots_raw, list):
            with capsys.disabled():
                print(f"[product-slots] case {idx}: invalid slots payload; skipping")
            continue
        slots_raw_list = cast(list[object], slots_raw)
        slot_entries: list[dict[str, str]] = []
        invalid_entry = False
        for entry in slots_raw_list:
            if not _is_dict_of_str(entry):
                invalid_entry = True
                break
            slot_entries.append(entry)
        if invalid_entry:
            with capsys.disabled():
                print(f"[product-slots] case {idx}: invalid slots payload; skipping")
            continue

        try:
            _, product_slots = gemini_runner.select_product_slots(
                slot_entries,
                case.get("product_prompt", ""),
                project_root,
                config,
                debug=False,
            )
        except Exception as exc:
            with capsys.disabled():
                print(f"[product-slots] case {idx}: gemini call failed: {exc}")
            continue

        expected_set = set(expected_slots)
        actual_set = set(product_slots)
        union = expected_set | actual_set
        if not union:
            score = 1.0
        else:
            score = len(expected_set & actual_set) / len(union)

        total_cases += 1
        total_score += score
        accuracy_pct = score * 100.0
        with capsys.disabled():
            print(
                "[product-slots] case {idx}: accuracy={accuracy:.1f}% "
                "expected={expected} actual={actual} product_prompt={prompt}".format(
                    idx=idx,
                    accuracy=accuracy_pct,
                    expected=expected_slots,
                    actual=product_slots,
                    prompt=case.get("product_prompt", ""),
                )
            )

    overall = (total_score / total_cases) * 100.0 if total_cases else 0.0
    with capsys.disabled():
        print(f"[product-slots] overall accuracy={overall:.1f}% ({total_cases} cases)")
