from __future__ import annotations

import unittest
from pathlib import Path

from airadio.cli import _build_parser


class CliParserTests(unittest.TestCase):
    def test_run_flags_work_before_or_after_subcommand(self) -> None:
        before = _build_parser().parse_args(["-v", "run"])
        after = _build_parser().parse_args(["run", "-v"])
        self.assertTrue(before.verbose)
        self.assertTrue(after.verbose)

    def test_quiet_flag_is_not_overwritten_by_subcommand(self) -> None:
        before = _build_parser().parse_args(["-q", "run"])
        after = _build_parser().parse_args(["run", "-q"])
        self.assertTrue(before.quiet)
        self.assertTrue(after.quiet)

    def test_home_works_after_run(self) -> None:
        parsed = _build_parser().parse_args(["run", "--home", "/tmp/example-station"])
        self.assertEqual(parsed.home, Path("/tmp/example-station"))

    def test_interstitial_provenance_commands_parse(self) -> None:
        info = _build_parser().parse_args(
            ["interstitials", "info", "audio/ads/voice/example.wav"]
        )
        lyrics = _build_parser().parse_args(
            ["interstitials", "lyrics", "example.wav"]
        )
        audit = _build_parser().parse_args(["interstitials", "audit"])
        self.assertEqual(info.interstitial_command, "info")
        self.assertEqual(lyrics.interstitial_command, "lyrics")
        self.assertEqual(audit.interstitial_command, "audit")


if __name__ == "__main__":
    unittest.main()
