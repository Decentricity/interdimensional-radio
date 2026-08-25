from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from airadio import interstitial_gen, interstitial_provenance


class InterstitialProvenanceTests(unittest.TestCase):
    def _paths(self, raw_home: str) -> tuple[Path, Path, Path]:
        home = Path(raw_home)
        audio = home / "interstitials/audio/ads/voice/test ad.wav"
        script = home / "interstitials/scripts/ads/test ad.txt"
        audio.parent.mkdir(parents=True)
        script.parent.mkdir(parents=True)
        script.write_text("Buy one moon, receive another moon.\n", encoding="utf-8")
        return home, audio, script

    def test_record_can_recover_exact_lyrics_and_archived_audio(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home, audio, script = self._paths(raw_home)
            audio.write_bytes(b"first wave")
            lyrics = "[verse]\nBuy one moon, receive another moon.\n"
            record = interstitial_provenance.record_generation(
                home,
                audio,
                lyrics=lyrics,
                kind="ads",
                style="voice",
                backend="minimax-music3",
                source_script=script,
                seed=1600,
                duration_s=8,
            )

            self.assertEqual(interstitial_provenance.read_lyrics(audio), lyrics)
            history_audio = home / record["audio"]["history_path"]
            self.assertEqual(history_audio.read_bytes(), b"first wave")
            self.assertTrue(interstitial_provenance.provenance_sidecar_path(audio).is_file())
            self.assertEqual(interstitial_provenance.audit(home), [])

    def test_regeneration_preserves_both_successful_versions(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home, audio, script = self._paths(raw_home)
            audio.write_bytes(b"first wave")
            first = interstitial_provenance.record_generation(
                home,
                audio,
                lyrics="[verse]\nFirst script.\n",
                kind="ads",
                style="voice",
                backend="minimax-music3",
                source_script=script,
                seed=1,
            )
            audio.write_bytes(b"second wave")
            second = interstitial_provenance.record_generation(
                home,
                audio,
                lyrics="[verse]\nSecond script.\n",
                kind="ads",
                style="voice",
                backend="minimax-music3",
                source_script=script,
                seed=2,
            )

            catalog = json.loads(
                interstitial_provenance.catalog_path(home).read_text(encoding="utf-8")
            )
            entry = catalog["clips"]["interstitials/audio/ads/voice/test ad.wav"]
            self.assertEqual(
                entry["generation_ids"],
                [first["generation_id"], second["generation_id"]],
            )
            self.assertEqual(second["supersedes"], first["generation_id"])
            self.assertEqual(
                (home / first["audio"]["history_path"]).read_bytes(), b"first wave"
            )
            self.assertEqual(
                (home / second["audio"]["history_path"]).read_bytes(), b"second wave"
            )

    def test_audit_detects_tampered_lyrics(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home, audio, script = self._paths(raw_home)
            audio.write_bytes(b"wave")
            interstitial_provenance.record_generation(
                home,
                audio,
                lyrics="[verse]\nOriginal.\n",
                kind="ads",
                style="voice",
                backend="minimax-music3",
                source_script=script,
            )
            interstitial_provenance.lyrics_sidecar_path(audio).write_text(
                "[verse]\nChanged.\n", encoding="utf-8"
            )
            self.assertTrue(
                any("lyrics hash" in issue.problem for issue in interstitial_provenance.audit(home))
            )

    def test_audit_verifies_older_archived_generations(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home, audio, script = self._paths(raw_home)
            audio.write_bytes(b"first wave")
            first = interstitial_provenance.record_generation(
                home,
                audio,
                lyrics="[verse]\nFirst.\n",
                kind="ads",
                style="voice",
                backend="minimax-music3",
                source_script=script,
            )
            audio.write_bytes(b"second wave")
            interstitial_provenance.record_generation(
                home,
                audio,
                lyrics="[verse]\nSecond.\n",
                kind="ads",
                style="voice",
                backend="minimax-music3",
                source_script=script,
            )
            (home / first["audio"]["history_path"]).write_bytes(b"tampered")
            self.assertTrue(
                any(
                    "history audio hash mismatch" in issue.problem
                    for issue in interstitial_provenance.audit(home)
                )
            )

    def test_failed_generation_leaves_previous_audio_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home, audio, script = self._paths(raw_home)
            audio.write_bytes(b"existing wave")
            with mock.patch.object(
                interstitial_gen.music3, "generate", side_effect=RuntimeError("failed")
            ):
                with self.assertRaisesRegex(RuntimeError, "failed"):
                    interstitial_gen.generate_voice_clip(
                        script,
                        audio,
                        home=home,
                        kind="ads",
                        seed=1600,
                        verbose=False,
                    )
            self.assertEqual(audio.read_bytes(), b"existing wave")
            self.assertFalse(
                interstitial_provenance.provenance_sidecar_path(audio).exists()
            )

    def test_successful_generation_records_the_exact_music3_input(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home, audio, script = self._paths(raw_home)

            def generate(**kwargs: object) -> None:
                Path(kwargs["out"]).write_bytes(b"generated wave")

            with mock.patch.object(
                interstitial_gen.music3, "generate", side_effect=generate
            ):
                interstitial_gen.generate_voice_clip(
                    script,
                    audio,
                    home=home,
                    kind="ads",
                    seed=1600,
                    verbose=False,
                )
            self.assertEqual(audio.read_bytes(), b"generated wave")
            self.assertEqual(
                interstitial_provenance.read_lyrics(audio),
                "[verse]\nBuy one moon, receive another moon.\n",
            )
            self.assertEqual(interstitial_provenance.audit(home), [])

    def test_relocated_audio_symlink_uses_the_real_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            logical = base / "project"
            runtime = base / "runtime"
            logical_interstitials = logical / "interstitials"
            real_audio = runtime / "interstitials/audio"
            logical_interstitials.mkdir(parents=True)
            real_audio.mkdir(parents=True)
            (logical_interstitials / "audio").symlink_to(real_audio, target_is_directory=True)
            audio = real_audio / "ads/voice/example.wav"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"wave")

            interstitial_provenance.record_generation(
                logical,
                audio,
                lyrics="[verse]\nExample.\n",
                kind="ads",
                style="voice",
                backend="minimax-music3",
            )

            self.assertTrue(
                (runtime / "interstitials/provenance/catalog.json").is_file()
            )
            self.assertEqual(interstitial_provenance.audit(logical), [])


if __name__ == "__main__":
    unittest.main()
