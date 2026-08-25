from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from airadio import lyricist
from airadio import song_title


class LyricistTests(unittest.TestCase):
    def test_line_rules_are_phrase_grammars(self) -> None:
        grammar = lyricist.load_grammar()
        for symbol in (
            "intro-line",
            "verse-line",
            "verse-turn-line",
            "title-image-line",
            "pre-line",
            "chorus-line",
            "bridge-line",
            "outro-line",
        ):
            for rule in grammar[symbol]:
                self.assertIn("#", rule, f"#{symbol}# contains a canned line: {rule}")

    def test_optional_easter_eggs_are_reachable_from_the_verse_grammar(self) -> None:
        grammar = lyricist.load_grammar()
        expected = {
            "hedgehog",
            "hedgey hog",
            "decentricity",
            "wassie",
            "crypto twitter",
            "Indonesia",
            "Jakarta",
            "cyberpunk",
            "expert systems",
            "Pandu",
        }
        self.assertEqual(set(grammar["easter-egg"]), expected)
        self.assertTrue(any("#easter-egg#" in rule for rule in grammar["verse-line"]))

    def test_many_complete_lyrics_are_unique_and_fully_expanded(self) -> None:
        lyrics = [lyricist.compose_lyrics("Velvet Garden", lyric_id) for lyric_id in range(500)]
        self.assertEqual(len(lyrics), len(set(lyrics)))
        self.assertTrue(all("#" not in lyric for lyric in lyrics))
        self.assertGreater(len({lyric.splitlines()[0] for lyric in lyrics}), 1)

    def test_generated_lines_avoid_invalid_article_and_location_combinations(self) -> None:
        for lyric_id in range(2_000):
            lyrics = lyricist.compose_lyrics("Signals After Rain", lyric_id)
            self.assertNotRegex(lyrics, r"\b[Aa] (?:amber|indigo)\b")
            self.assertNotIn("in the county line", lyrics)
            self.assertNotRegex(lyrics, r"^The .* still (?:smells|tastes) of ", re.MULTILINE)
            self.assertNotRegex(
                lyrics,
                r"This time I (?:carry|release|remember|believe|follow|choose|welcome|outgrow) "
                r"(?:toward|away from|past|into|under|until|without|where)",
            )

    def test_same_id_and_title_are_reproducible(self) -> None:
        first = lyricist.compose_lyrics("Copper Horizon", 8128)
        second = lyricist.compose_lyrics("Copper Horizon", 8128)
        self.assertEqual(first, second)

    def test_lyric_id_is_part_of_library_filename(self) -> None:
        first = song_title.song_filename("Velvet Garden", 42, lyric_id=7)
        second = song_title.song_filename("Velvet Garden", 42, lyric_id=8)
        self.assertNotEqual(first, second)
        self.assertIn("l00000007", first)

    def test_reservation_persists_id_and_full_text_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home = Path(raw_home)
            first = lyricist.reserve_lyrics(home, "Quiet River")
            second = lyricist.reserve_lyrics(home, "Quiet River")
            self.assertNotEqual(first.text, second.text)
            self.assertNotEqual(first.sha256, second.sha256)
            state = json.loads((home / lyricist.STATE_FILE).read_text(encoding="utf-8"))
            self.assertEqual(state["next_lyric_id"], 2)
            self.assertEqual(set(state["used_sha256"]), {first.sha256, second.sha256})


if __name__ == "__main__":
    unittest.main()
