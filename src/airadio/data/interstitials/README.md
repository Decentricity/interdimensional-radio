# Interdimensional Radio — prerecorded interstitials

Airadio records new clips with neighboring `.lyrics.txt` and
`.provenance.json` files plus append-only history under
`interstitials/provenance/`. Use `airadio interstitials lyrics`, `info`, or
`audit` to inspect and verify them.

Short clips played when the next song is still generating.

**Mascot:** Miss Hedgey Hog — a little pink hedgehog. Station mascot only, **not** the DJ or announcer. See [BRAND.md](BRAND.md).

## Layout

```
interstitials/
  manifest.json
  scripts/
    ads/                 # 10 ad scripts
    station-id/          # 10 station ID scripts
    dj-chatter/          # 20 DJ lines (Piper)
  audio/
    ads/
      voice/             # dry spoken ads (female announcer)
      jingle/            # minisong ads (female announcer)
    station-id/
      voice/             # dry spoken IDs — male announcer (kept)
      jingle/            # minisong IDs — female announcer
    dj-chatter/          # 20 Piper WAVs
  prompts/
    voice-only.caption.txt
    radio-ad.caption.txt
    station-id.caption.txt
```

## Regenerate

```bash
python3 ~/music/bin/generate-interstitials.py music3-both    # 40 Music3 clips (default)
python3 ~/music/bin/generate-interstitials.py music3-voice    # voice-only ads + IDs only
python3 ~/music/bin/generate-interstitials.py music3-jingle   # jingle ads + IDs only
python3 ~/music/bin/generate-interstitials.py dj-music3 --force     # Music3 DJ chatter (voice only)
python3 ~/music/bin/generate-interstitials.py dj-music3 --reshuffle-genders --force
python3 ~/music/bin/generate-interstitials.py music3-remaining-female  # finish missing clips (female voice)
python3 ~/music/bin/generate-interstitials.py music3-both --force  # regenerate all (destructive)
```

Skips existing WAVs unless `--force`. **Male voice-only station IDs in `station-id/voice/` are preserved** — female variants go to separate paths (`jingle/`, `ads/`).
