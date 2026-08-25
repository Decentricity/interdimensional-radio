"""Generate interstitial audio clips via MiniMax Music 3."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

from airadio import interstitial_provenance, music3
from airadio.paths import bundled_interstitials_dir

SEED_BASE = {
    ("ads", "voice"): 1600,
    ("station-id", "voice"): 1500,
}


def prompts_dir() -> Path:
    return bundled_interstitials_dir() / "prompts"


def duration_for_text(text: str, *, kind: str) -> float:
    words = len(text.split())
    if kind == "ads":
        return round(max(8.0, min(10.0, words / 2.8 + 1.5)), 1)
    return round(max(5.0, min(12.0, words / 2.2 + 1.5)), 1)


def play_audio(path: Path) -> None:
    for cmd in (["pw-play", str(path)], ["aplay", "-q", str(path)]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, check=False)
            return
    raise RuntimeError("no audio player found (need pw-play or aplay)")


def generate_voice_clip(
    script: Path,
    out_wav: Path,
    *,
    home: Path,
    kind: str,
    seed: int,
    verbose: bool = True,
) -> Path:
    text = script.read_text(encoding="utf-8").strip()
    caption = prompts_dir() / "voice-only.caption.txt"
    work = out_wav.parent / ".work"
    work.mkdir(parents=True, exist_ok=True)
    lyrics = work / f"{script.stem}.lyrics.txt"
    lyrics_text = f"[verse]\n{text}\n"
    lyrics.write_text(lyrics_text, encoding="utf-8")
    duration = int(duration_for_text(text, kind=kind))
    temporary = work / f".{out_wav.name}.{uuid.uuid4().hex}.tmp.wav"
    if verbose:
        print(f"  script: {text[:72]}{'…' if len(text) > 72 else ''}", flush=True)
    try:
        music3.generate(
            lyrics=lyrics,
            caption=caption,
            duration=duration,
            seed=seed,
            out=temporary,
            play=False,
            verbose=verbose,
        )
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError(f"Music3 did not produce audio for {script}")
        temporary.replace(out_wav)
        interstitial_provenance.record_generation(
            home,
            out_wav,
            lyrics=lyrics_text,
            kind=kind,
            style="voice",
            backend="minimax-music3",
            source_script=script,
            caption=caption,
            seed=seed,
            duration_s=duration,
        )
    finally:
        temporary.unlink(missing_ok=True)
    return out_wav
