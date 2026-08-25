"""Random two-word song titles from paired word lists."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from airadio.paths import prompts_dir


def _prompt(name: str) -> Path:
    return prompts_dir() / name


def load_words() -> dict[str, list[str]]:
    data = json.loads(_prompt("song-title-words.json").read_text(encoding="utf-8"))
    first = data.get("first", [])
    second = data.get("second", [])
    if len(first) != 32 or len(second) != 32:
        raise ValueError("song-title-words.json must have 32 first and 32 second words")
    return {"first": first, "second": second}


def random_title(rng: random.Random | None = None) -> str:
    pick = rng or random
    words = load_words()
    return f"{pick.choice(words['first'])} {pick.choice(words['second'])}"


def title_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower().strip())
    slug = slug.strip("-")
    return slug or "untitled"


def song_filename(title: str, seed: int, lyric_id: int | None = None) -> str:
    suffix = f"-l{lyric_id:08d}" if lyric_id is not None else ""
    return f"{title_slug(title)}{seed}{suffix}.wav"


def build_caption(title: str, *, base_path: Path | None = None) -> str:
    if base_path is None:
        base_path = _prompt("normie-control.caption.txt")
    base = base_path.read_text(encoding="utf-8").strip()
    return (
        f"{base}\n\n"
        f"Song title: {title}\n"
        f'The song is titled "{title}". Mood, imagery, and lyrics should grow from this title. '
        "Do not simply repeat the song title or its two words as the main vocal hook."
    )
