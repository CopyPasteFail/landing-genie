from pathlib import Path

from landing_genie.site_paths import normalize_site_dir


def test_normalize_site_dir_flattens_nested(tmp_path: Path) -> None:
    nested = tmp_path / "sites" / "sluggy" / "sites" / "sluggy"
    nested.mkdir(parents=True)
    (nested / "index.html").write_text("ok", encoding="utf-8")
    (nested / "styles.css").write_text("body{}", encoding="utf-8")

    site_dir = normalize_site_dir("sluggy", tmp_path)

    assert (site_dir / "index.html").exists()
    assert (site_dir / "styles.css").exists()
    assert not (site_dir / "sites" / "sluggy").exists()
