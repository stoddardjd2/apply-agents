"""Give this workspace its own Camoufox browser install (not AppData).

Python camoufox hardcodes INSTALL_DIR to %LOCALAPPDATA%\\camoufox\\... and, when
the 0.5 compat flag is missing, deletes that whole tree on every launch. A second
Camoufox on the same PC then holds omni.ja open → PermissionError.

Override INSTALL_DIR (and multiversion paths derived from it) before launching.
"""

from __future__ import annotations

import os
from pathlib import Path

_APPLIED = False


def camoufox_install_dir() -> Path:
    raw = (os.getenv("CAMOUFOX_INSTALL_DIR") or ".cache/camoufox-install").strip()
    return Path(raw).expanduser().resolve()


def apply_camoufox_install_dir(*, install_dir: Path | None = None) -> Path:
    """Patch camoufox.pkgman / multiversion to use a project-local install."""
    global _APPLIED
    root = (install_dir or camoufox_install_dir()).resolve()
    root.mkdir(parents=True, exist_ok=True)

    import camoufox.pkgman as pkgman

    pkgman.INSTALL_DIR = root

    # multiversion binds paths at import time — rebind after pkgman patch.
    import camoufox.multiversion as multiversion

    multiversion.BROWSERS_DIR = root / "browsers"
    multiversion.CONFIG_FILE = root / "config.json"
    multiversion.REPO_CACHE_FILE = root / "repo_cache.json"
    multiversion.COMPAT_FLAG = root / ".0.5_FLAG"

    if not _APPLIED:
        print(f"Camoufox install dir: {root}", flush=True)
        _APPLIED = True
    return root
