"""Random two-word song titles from paired word lists."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from airadio import lyricist
from airadio.paths import prompts_dir

INSTRUMENTAL_CHANCE = 5  # 1 in N songs


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


def split_title(title: str) -> tuple[str, str]:
    parts = title.split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], parts[1]


def roll_instrumental(rng: random.Random | None = None) -> bool:
    pick = rng or random
    return pick.randint(1, INSTRUMENTAL_CHANCE) == 1


def build_caption(title: str, *, instrumental: bool = False, base_path: Path | None = None) -> str:
    if base_path is None:
        name = (
            "normie-control.caption.instrumental.txt"
            if instrumental
            else "normie-control.caption.txt"
        )
        base_path = _prompt(name)
    base = base_path.read_text(encoding="utf-8").strip()
    mood = (
        "Mood and arrangement should grow from this title."
        if instrumental
        else (
            "Mood, imagery, and lyrics should grow from this title. "
            "Do not simply repeat the song title or its two words as the main vocal hook."
        )
    )
    return (
        f"{base}\n\n"
        f"Song title: {title}\n"
        f'The song is titled "{title}". {mood}'
    )


def build_lyrics(
    title: str,
    *,
    instrumental: bool = False,
    lyric_id: int | None = None,
    template_path: Path | None = None,
) -> str:
    if instrumental:
        path = template_path or _prompt("normie-control.lyrics.instrumental.template.txt")
        return path.read_text(encoding="utf-8").strip()
    if template_path is not None:
        word1, word2 = split_title(title)
        return template_path.read_text(encoding="utf-8").format(
            title=title,
            word1=word1.lower(),
            word2=word2.lower(),
        )
    if lyric_id is None:
        raise ValueError("vocal lyrics require a reserved lyric_id")
    return lyricist.compose_lyrics(title, lyric_id)
