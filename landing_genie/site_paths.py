from __future__ import annotations

import re
import shutil
from pathlib import Path

_SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


def normalize_slug(raw_slug: str) -> str:
    """
    Normalize and validate a user-supplied slug.

    - Lowercases
    - Replaces spaces with hyphens
    - Requires only [a-z0-9-] to avoid path traversal and invalid DNS labels
    """
    slug = raw_slug.strip().lower().replace(" ", "-")
    if not slug:
        raise ValueError("Slug cannot be empty.")
    if not _SLUG_PATTERN.fullmatch(slug):
        raise ValueError("Slug may only contain lowercase letters, digits, and hyphens (a-z, 0-9, '-').")
    return slug


def normalize_site_dir(slug: str, project_root: Path) -> Path:
    """
    Ensure the site's files live directly under sites/<slug>/.

    Gemini occasionally nests output under sites/<slug>/sites/<slug>/; when detected,
    move generated files up one level and clean up the extra directories.
    """
    safe_slug = normalize_slug(slug)
    site_dir = project_root / "sites" / safe_slug
    nested = site_dir / "sites" / safe_slug

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
