"""Recursive grammar lyric composition inspired by Galaxy Kate's Tracery."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from airadio.storage import atomic_write_json

STATE_FILE = "lyric-state.json"
MAX_EXPANSION_DEPTH = 40
MAX_UNIQUE_LINE_ATTEMPTS = 200
_TAG = re.compile(r"#([A-Za-z][A-Za-z0-9_-]*)#")
_state_lock = threading.Lock()


@dataclass(frozen=True)
class ReservedLyrics:
    lyric_id: int
    text: str
    sha256: str


class Grammar:
    """Deterministic expander for Tracery's symbol/rules pattern.

    Airadio only needs recursive ``#symbol#`` expansion and song-local bound
    symbols. It deliberately does not duplicate Tracery's modifiers, actions,
    visualization tree, or JavaScript runtime.
    """

    def __init__(self, rules: dict[str, list[str]], rng: random.Random) -> None:
        self.rules = rules
        self.rng = rng
        self.bindings: dict[str, str] = {}
        self.used_templates: dict[str, set[str]] = {}

    def choose(self, symbol: str) -> str:
        options = self.rules.get(symbol)
        if not options:
            raise ValueError(f"lyric grammar has no rules for #{symbol}#")
        return self.rng.choice(options)

    def expand_symbol(self, symbol: str) -> str:
        if symbol in self.bindings:
            return self.bindings[symbol]
        return self.expand(self.choose(symbol))

    def expand(self, text: str, *, depth: int = 0) -> str:
        if depth > MAX_EXPANSION_DEPTH:
            raise RuntimeError("lyric grammar exceeded its recursion limit")

        def replace(match: re.Match[str]) -> str:
            symbol = match.group(1)
            if symbol in self.bindings:
                return self.bindings[symbol]
            return self.expand(self.choose(symbol), depth=depth + 1)

        expanded = _TAG.sub(replace, text)
        if _TAG.search(expanded):
            return self.expand(expanded, depth=depth + 1)
        return " ".join(expanded.split())


def grammar_path() -> Path:
    override = os.environ.get("AIRADIO_LYRICS_GRAMMAR")
    if override:
        return Path(override).expanduser().resolve()
    return Path(str(files("airadio").joinpath("data", "lyrics-grammar.json")))


def load_grammar() -> dict[str, list[str]]:
    raw = json.loads(grammar_path().read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("lyrics-grammar.json must contain an object")
    rules: dict[str, list[str]] = {}
    for symbol, options in raw.items():
        if not isinstance(options, list) or not options or not all(
            isinstance(option, str) and option for option in options
        ):
            raise ValueError(f"lyrics-grammar.json #{symbol}# must be a non-empty string list")
        rules[str(symbol)] = options
    return rules


def _seed_for(title: str, lyric_id: int) -> int:
    digest = hashlib.sha256(f"airadio-lyrics-v2\0{lyric_id}\0{title}".encode()).digest()
    return int.from_bytes(digest[:16], "big")


def _bind_song_world(grammar: Grammar, title: str) -> None:
    words = title.split(maxsplit=1)
    grammar.bindings.update(
        {
            "title": title.lower(),
            "title-first": (words[0] if words else "open").lower(),
            "title-second": (
                words[1] if len(words) > 1 else words[0] if words else "road"
            ).lower(),
        }
    )
    # Tracery's push actions bind a generated symbol for consistent reuse. Do
    # that explicitly for the recurring physical world of this song.
    for symbol in (
        "setting",
        "near-place",
        "far-place",
        "weather",
        "color",
        "keepsake",
        "signal",
        "light-source",
        "time",
    ):
        grammar.bindings[symbol] = grammar.expand(grammar.choose(symbol))


def _unique_lines(grammar: Grammar, symbol: str, count: int, seen: set[str]) -> list[str]:
    options = grammar.rules.get(symbol)
    if not options:
        raise ValueError(f"lyric grammar has no rules for #{symbol}#")
    used_templates = grammar.used_templates.setdefault(symbol, set())
    available = [template for template in options if template not in used_templates]
    if len(available) < count:
        raise RuntimeError(
            f"#{symbol}# needs {count} unused templates but only {len(available)} remain"
        )
    grammar.rng.shuffle(available)
    lines: list[str] = []
    for template in available:
        for _attempt in range(MAX_UNIQUE_LINE_ATTEMPTS):
            line = grammar.expand(template)
            line = line[:1].upper() + line[1:]
            key = line.casefold()
            if key not in seen:
                seen.add(key)
                lines.append(line)
                used_templates.add(template)
                break
        if len(lines) == count:
            return lines
    raise RuntimeError(f"could not produce another unique #{symbol}# line")


def compose_lyrics(title: str, lyric_id: int) -> str:
    """Build a song from recursive phrase grammar and combinatorial song form."""
    if lyric_id < 0:
        raise ValueError("lyric_id must be non-negative")
    grammar = Grammar(load_grammar(), random.Random(_seed_for(title, lyric_id)))
    _bind_song_world(grammar, title)
    form = grammar.choose("song-form").split()
    seen: set[str] = set()
    chorus = _unique_lines(grammar, "chorus-line", 4, seen)
    pre_chorus = _unique_lines(grammar, "pre-line", 2, seen)
    rendered: list[str] = []
    verse_number = 0
    for section in form:
        rendered.append(f"[{section}]")
        if section == "intro":
            rendered.extend(_unique_lines(grammar, "intro-line", 2, seen))
        elif section == "verse":
            verse_number += 1
            lines = _unique_lines(grammar, "verse-line", 3, seen)
            if verse_number == 1:
                title_line = grammar.expand_symbol("title-image-line")
                title_line = title_line[:1].upper() + title_line[1:]
                seen.add(title_line.casefold())
                lines.append(title_line)
            else:
                lines.extend(_unique_lines(grammar, "verse-turn-line", 1, seen))
            rendered.extend(lines)
        elif section == "pre-chorus":
            rendered.extend(pre_chorus)
        elif section == "chorus":
            rendered.extend(chorus)
        elif section == "bridge":
            rendered.extend(_unique_lines(grammar, "bridge-line", 3, seen))
        elif section == "outro":
            rendered.extend(_unique_lines(grammar, "outro-line", 2, seen))
        else:
            raise ValueError(f"unsupported lyric section in song form: {section}")
    return "\n".join(rendered)


def lyrics_sha256(lyrics: str) -> str:
    return hashlib.sha256(lyrics.encode("utf-8")).hexdigest()


def _catalog_hashes(home: Path) -> set[str]:
    catalog = home / "library" / "catalog.json"
    if not catalog.is_file():
        return set()
    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return {
        str(entry["lyrics_sha256"])
        for entry in data.get("songs", [])
        if isinstance(entry, dict) and entry.get("lyrics_sha256")
    }


def reserve_lyrics(home: Path, title: str) -> ReservedLyrics:
    """Reserve a lyric whose complete text has never been used by this station."""
    state_path = home / STATE_FILE
    with _state_lock:
        if state_path.is_file():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                next_id = int(state["next_lyric_id"])
                used = {str(value) for value in state.get("used_sha256", [])}
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(f"invalid lyric state file: {state_path}") from exc
        else:
            next_id = 0
            used = set()
        used.update(_catalog_hashes(home))

        while True:
            lyrics = compose_lyrics(title, next_id)
            digest = lyrics_sha256(lyrics)
            reserved_id = next_id
            next_id += 1
            if digest not in used:
                break

        used.add(digest)
        atomic_write_json(
            state_path,
            {"version": 2, "next_lyric_id": next_id, "used_sha256": sorted(used)},
        )
        return ReservedLyrics(reserved_id, lyrics, digest)
