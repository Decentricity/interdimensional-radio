from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from airadio import setup


class SetupReadinessTests(unittest.TestCase):
    def test_station_is_ready_without_a_library_song(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home = Path(raw_home)
            ad = home / "interstitials/audio/ads/voice/ad.wav"
            station_id = home / "interstitials/audio/station-id/voice/id.wav"
            ad.parent.mkdir(parents=True)
            station_id.parent.mkdir(parents=True)
            ad.write_bytes(b"placeholder")
            station_id.write_bytes(b"placeholder")
            self.assertTrue(setup.is_ready(home))


if __name__ == "__main__":
    unittest.main()
