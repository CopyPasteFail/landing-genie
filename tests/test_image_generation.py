import os
from pathlib import Path

import pytest

from landing_genie.config import Config
from landing_genie.image_generator import generate_images_for_site


def _require_env_vars(names: list[str]) -> None:
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing required env vars for integration test: {', '.join(missing)}")


def test_image_generation_smoke(tmp_path: Path) -> None:
    """Confirm the Python image path works end-to-end with a minimal prompt."""
    _require_env_vars(["GEMINI_API_KEY"])
    config = Config.load()

    slug = "image-smoke"
    site_dir = tmp_path / "sites" / slug
    assets_dir = site_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    index_path = site_dir / "index.html"
    index_path.write_text('<html><body><img src="assets/test.png" alt="tiny test"></body></html>', encoding="utf-8")

    created = generate_images_for_site(
        slug=slug,
        product_prompt="tiny image smoke test",
        project_root=tmp_path,
        config=config,
        overwrite=True,
    )

    assert len(created) == 1, f"Expected one image to be generated, got {len(created)}"
    assert created[0].exists(), "Generated image file missing on disk"
    assert created[0].stat().st_size > 0, "Generated image file is empty"
