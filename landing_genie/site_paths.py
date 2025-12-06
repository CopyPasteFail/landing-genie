from __future__ import annotations

import shutil
from pathlib import Path


def normalize_site_dir(slug: str, project_root: Path) -> Path:
    """
    Ensure the site's files live directly under sites/<slug>/.

    Gemini occasionally nests output under sites/<slug>/sites/<slug>/; when detected,
    move generated files up one level and clean up the extra directories.
    """
    site_dir = project_root / "sites" / slug
    nested = site_dir / "sites" / slug

    if nested.exists():
        for path in nested.iterdir():
            dest = site_dir / path.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            path.replace(dest)

        # Attempt to remove the now-empty nested directories; ignore if not empty.
        for path in (nested, nested.parent):
            try:
                path.rmdir()
            except OSError:
                pass

    return site_dir
