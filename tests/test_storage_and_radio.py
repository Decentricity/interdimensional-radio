from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from airadio import radio
from airadio.storage import atomic_write_json


class StorageTests(unittest.TestCase):
    def test_atomic_json_replaces_complete_document(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            path = Path(raw_home) / "nested/state.json"
            atomic_write_json(path, {"value": 1})
            atomic_write_json(path, {"value": 2, "items": [1, 2, 3]})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"value": 2, "items": [1, 2, 3]},
            )
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_invalid_catalog_is_backed_up_before_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            cfg = radio.Config(Path(raw_home))
            cfg.catalog.write_text("{not json", encoding="utf-8")
            with mock.patch.object(radio, "_rebuilt_catalog", return_value={"songs": []}):
                catalog = radio.load_catalog(cfg)
            self.assertEqual(catalog, {"songs": []})
            self.assertEqual(len(list(cfg.library.glob("catalog.corrupt-*.json"))), 1)


class RadioStateMachineTests(unittest.TestCase):
    def test_slow_generations_do_not_recurse(self) -> None:
        song = Path("/tmp/generated-song.wav")

        class FakeGenerator:
            bridges = 0

            def waiting_seconds(self) -> float:
                return 1.0

            def ready(self) -> bool:
                return self.bridges >= 1500

            def result(self) -> Path:
                return song

        gen = FakeGenerator()

        def bridge(*_args: object) -> None:
            gen.bridges += 1

        with tempfile.TemporaryDirectory() as raw_home:
            cfg = radio.Config(Path(raw_home))
            with (
                mock.patch.object(radio, "play_wait_session", return_value=(None, song)),
                mock.patch.object(radio, "play_bridge_into_song", side_effect=bridge),
                mock.patch.object(radio, "log"),
            ):
                result, already_played = radio.transition_with_fill(
                    gen, cfg, Path(raw_home)
                )
        self.assertEqual(result, song)
        self.assertTrue(already_played)
        self.assertEqual(gen.bridges, 1500)

    def test_runtime_tool_check_accepts_either_audio_player(self) -> None:
        available = {"ffmpeg", "ffprobe", "pw-play"}
        with mock.patch.object(radio.shutil, "which", side_effect=lambda name: name if name in available else None):
            self.assertEqual(radio.missing_runtime_tools(), [])

    def test_keyboard_interrupt_releases_playback_and_station_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home = Path(raw_home)
            with (
                mock.patch.object(radio.music3, "require_ready", return_value=True),
                mock.patch.object(radio, "missing_runtime_tools", return_value=[]),
                mock.patch("airadio.setup.is_ready", return_value=True),
                mock.patch.object(radio, "acquire_radio_lock"),
                mock.patch.object(radio, "release_radio_lock") as release,
                mock.patch.object(radio, "stop_stray_radio_processes"),
                mock.patch.object(radio, "stop_playback") as stop,
                mock.patch.object(radio, "ensure_catalog_hashes"),
                mock.patch.object(radio, "import_staging_songs", return_value=0),
                mock.patch.object(radio, "cleanup_staging"),
                mock.patch.object(radio, "bootstrap_first_song", side_effect=KeyboardInterrupt),
                mock.patch.object(radio, "log"),
            ):
                result = radio.run(home)
            self.assertEqual(result, 130)
            release.assert_called_once()
            self.assertGreaterEqual(stop.call_count, 2)


if __name__ == "__main__":
    unittest.main()
