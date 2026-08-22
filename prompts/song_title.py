#!/usr/bin/env python3
"""Random two-word song titles from paired word lists."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent
WORDS_FILE = PROMPTS / "song-title-words.json"
LYRICS_TEMPLATE = PROMPTS / "normie-control.lyrics.template.txt"
CAPTION_BASE = PROMPTS / "normie-control.caption.txt"
CAPTION_INSTRUMENTAL = PROMPTS / "normie-control.caption.instrumental.txt"
LYRICS_INSTRUMENTAL = PROMPTS / "normie-control.lyrics.instrumental.template.txt"

INSTRUMENTAL_CHANCE = 5  # 1 in N songs


def load_words() -> dict[str, list[str]]:
    data = json.loads(WORDS_FILE.read_text(encoding="utf-8"))
    first = data.get("first", [])
    second = data.get("second", [])
    if len(first) != 32 or len(second) != 32:
        raise ValueError(f"song-title-words.json must have 32 first and 32 second words")
    return {"first": first, "second": second}


def random_title(rng: random.Random | None = None) -> str:
    pick = rng or random
    words = load_words()
    return f"{pick.choice(words['first'])} {pick.choice(words['second'])}"


def title_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower().strip())
    slug = slug.strip("-")
    return slug or "untitled"


def song_filename(title: str, seed: int) -> str:
    """Library filename: slugified title phrase + numeric seed."""
    return f"{title_slug(title)}{seed}.wav"


def split_title(title: str) -> tuple[str, str]:
    parts = title.split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], parts[1]


def roll_instrumental(rng: random.Random | None = None) -> bool:
    """Return True for a 1-in-N instrumental generation."""
    pick = rng or random
    return pick.randint(1, INSTRUMENTAL_CHANCE) == 1


def build_caption(title: str, *, instrumental: bool = False, base_path: Path | None = None) -> str:
    if base_path is None:
        base_path = CAPTION_INSTRUMENTAL if instrumental else CAPTION_BASE
    base = base_path.read_text(encoding="utf-8").strip()
    mood = (
        "Mood and arrangement should grow from this title."
        if instrumental
        else "Mood, imagery, and lyrics should grow from this title."
    )
    return (
        f"{base}\n\n"
        f"Song title: {title}\n"
        f'The song is titled "{title}". {mood}'
    )


def build_lyrics(title: str, *, instrumental: bool = False, template_path: Path | None = None) -> str:
    if instrumental:
        return (template_path or LYRICS_INSTRUMENTAL).read_text(encoding="utf-8").strip()
    word1, word2 = split_title(title)
    template = (template_path or LYRICS_TEMPLATE).read_text(encoding="utf-8")
    return template.format(title=title, word1=word1, word2=word2)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate a random two-word song title")
    parser.add_argument("--count", type=int, default=1, help="number of titles to print")
    parser.add_argument("--seed", type=int, help="optional RNG seed")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    for _ in range(args.count):
        print(random_title(rng))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
