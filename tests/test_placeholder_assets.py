from pathlib import Path

from landing_genie.image_generator import ensure_placeholder_assets


def test_zero_byte_assets_are_replaced(tmp_path: Path) -> None:
    slug = "placeholder-test"
    site_dir = tmp_path / "sites" / slug
    assets_dir = site_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Simulate Gemini writing empty placeholder files.
    (assets_dir / "hero.png").write_bytes(b"")

    index_path = site_dir / "index.html"
    index_path.write_text(
        '<img src="assets/hero.png" alt="Hero"><img src="assets/feature-1.png" alt="Feature">',
        encoding="utf-8",
    )

    created = ensure_placeholder_assets(slug=slug, project_root=tmp_path)

    created_names = {path.name for path in created}
    assert {"hero.png", "feature-1.png"} == created_names

    for name in ("hero.png", "feature-1.png"):
        asset_path = assets_dir / name
        assert asset_path.exists()
        assert asset_path.stat().st_size > 0
