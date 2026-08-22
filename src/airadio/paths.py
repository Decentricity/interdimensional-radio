"""Resolve bundled package data and per-user runtime directories."""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path


def user_home() -> Path:
    """Runtime data root: library, staging, interstitial audio, logs."""
    for key in ("AIRADIO_HOME", "IDR_ROOT"):
        if env := os.environ.get(key):
            return Path(env).expanduser().resolve()
    cwd = Path.cwd()
    if (cwd / "library").is_dir() or (cwd / ".radio-staging").is_dir():
        return cwd.resolve()
    return Path.home() / ".local/share/airadio"


def package_data(*parts: str) -> Path:
    return Path(str(files("airadio").joinpath("data", *parts)))


def prompts_dir() -> Path:
    override = os.environ.get("AIRADIO_PROMPTS")
    if override:
        return Path(override).expanduser().resolve()
    return package_data("prompts")


def bundled_interstitials_dir() -> Path:
    return package_data("interstitials")


def library_dir(home: Path | None = None) -> Path:
    return (home or user_home()) / "library"


def staging_dir(home: Path | None = None) -> Path:
    return (home or user_home()) / ".radio-staging"


def interstitials_audio_dir(home: Path | None = None) -> Path:
    return (home or user_home()) / "interstitials" / "audio"


def ensure_user_layout(home: Path | None = None) -> Path:
    root = home or user_home()
    library_dir(root).mkdir(parents=True, exist_ok=True)
    interstitials_audio_dir(root).mkdir(parents=True, exist_ok=True)
    staging_dir(root).mkdir(parents=True, exist_ok=True)
    return root
