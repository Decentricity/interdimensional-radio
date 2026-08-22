#!/usr/bin/env python3
"""Generate and play Interdimensional Radio interstitials."""

from __future__ import annotations

import random
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/decentricity/music/interstitials")
SCRIPTS = ROOT / "scripts"
AUDIO = ROOT / "audio"
PROMPTS = ROOT / "prompts"
CAPTIONS = {
    ("ads", "voice"): PROMPTS / "voice-only.caption.txt",
    ("ads", "jingle"): PROMPTS / "radio-ad.caption.txt",
    ("station-id", "voice"): PROMPTS / "voice-only.caption.txt",
    ("station-id", "jingle"): PROMPTS / "station-id.caption.txt",
}
CAPTIONS_FEMALE = {
    ("ads", "voice"): PROMPTS / "voice-only-female.caption.txt",
    ("ads", "jingle"): PROMPTS / "radio-ad-female.caption.txt",
    ("station-id", "voice"): PROMPTS / "voice-only-female.caption.txt",
    ("station-id", "jingle"): PROMPTS / "station-id-female.caption.txt",
}
DJ_CAPTIONS = {
    "male": PROMPTS / "dj-voice-male.caption.txt",
    "female": PROMPTS / "dj-voice-female.caption.txt",
    "alien": PROMPTS / "dj-voice-alien.caption.txt",
}
DJ_GENDERS_FILE = ROOT / "dj-genders.json"
DJ_GENDER_CHOICES = ("male", "female", "alien")


def warm_cmd(*parts: str) -> list[str]:
    if shutil.which("airadio"):
        return ["airadio", "music3", *parts]
    script = Path(__file__).resolve().parent / "music3-warm"
    return [str(script), *parts]


PIPER_BIN = Path("/home/decentricity/companion-ai/.venv/bin/piper")
PIPER_VOICE_DIR = Path.home() / ".local/share/companion-ai/piper-voices"
PIPER_VOICE = PIPER_VOICE_DIR / "en_US-lessac-medium.onnx"
MANIFEST = ROOT / "manifest.json"

SEED_BASE = {
    ("ads", "voice"): 1600,
    ("ads", "jingle"): 1700,
    ("station-id", "voice"): 1500,
    ("station-id", "jingle"): 1800,
    ("dj-chatter", "voice"): 1900,
}


def play(path: Path) -> None:
    for cmd in (["pw-play", str(path)], ["aplay", "-q", str(path)]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, check=False)
            return
    raise RuntimeError("no audio player found")


def duration_for_text(text: str, *, kind: str, style: str) -> float:
    words = len(text.split())
    if kind == "dj-chatter":
        return round(max(5.0, min(11.0, words / 2.4 + 1.5)), 1)
    if kind == "ads":
        # Jingle ads collapse into radio-montage past ~10s; keep spots short.
        if style == "jingle":
            return round(max(7.0, min(9.5, words / 2.5 + 1.5)), 1)
        return round(max(8.0, min(10.0, words / 2.8 + 1.5)), 1)
    secs = words / 2.2 + 1.5
    return round(max(5.0, min(12.0, secs)), 1)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, **kwargs)


def music3_generate(
    script: Path,
    out_wav: Path,
    seed: int,
    *,
    kind: str,
    style: str,
    female: bool = False,
    dj_gender: str | None = None,
) -> None:
    text = script.read_text().strip()
    if kind == "dj-chatter" and dj_gender:
        caption = DJ_CAPTIONS[dj_gender]
    else:
        captions = CAPTIONS_FEMALE if female else CAPTIONS
        caption = captions[(kind, style)]
    work = PROMPTS / "work"
    work.mkdir(parents=True, exist_ok=True)
    lyrics = work / f"{kind}-{style}-{script.stem}.lyrics.txt"
    lyrics.write_text(f"[verse]\n{text}\n")
    run(
        warm_cmd(
            "gen",
            "--lyrics",
            str(lyrics),
            "--prompt",
            str(caption),
            "--duration",
            str(duration_for_text(text, kind=kind, style=style)),
            "--seed",
            str(seed),
            "--out",
            str(out_wav),
            "--no-play",
        )
    )


def piper_generate(script: Path, out_wav: Path) -> None:
    text = script.read_text().strip()
    piper = str(PIPER_BIN if PIPER_BIN.is_file() else shutil.which("piper") or "")
    if not piper:
        raise RuntimeError("piper not found")
    if not PIPER_VOICE.is_file():
        raise RuntimeError(f"piper voice missing: {PIPER_VOICE}")
    proc = subprocess.run(
        [
            piper,
            "-m",
            str(PIPER_VOICE),
            "-f",
            str(out_wav),
            "--data-dir",
            str(PIPER_VOICE_DIR),
            "--length_scale",
            "1.0",
            "--volume",
            "1.0",
        ],
        input=text,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or not out_wav.is_file():
        raise RuntimeError(f"piper failed for {script.name}: {proc.stderr.decode()}")


def load_dj_genders(*, reshuffle: bool = False) -> dict[str, str]:
    scripts = sorted((SCRIPTS / "dj-chatter").glob("*.txt"))
    if reshuffle or not DJ_GENDERS_FILE.is_file():
        rng = random.Random(20260822)
        genders = {s.stem: rng.choice(DJ_GENDER_CHOICES) for s in scripts}
        DJ_GENDERS_FILE.write_text(
            json.dumps(
                {
                    "note": "Random DJ gender per script for Music3 voice-only generation.",
                    "assigned_at": datetime.now(timezone.utc).isoformat(),
                    "genders": genders,
                },
                indent=2,
            )
            + "\n"
        )
        return genders
    data = json.loads(DJ_GENDERS_FILE.read_text())
    return dict(data.get("genders") or {})


def load_manifest() -> dict:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text())
    return {"generated_at": None, "items": []}


def save_manifest(data: dict) -> None:
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n")


def manifest_has(manifest: dict, audio: Path) -> bool:
    rel = str(audio.relative_to(ROOT))
    return any(item.get("audio") == rel for item in manifest.get("items", []))


def add_item(
    manifest: dict,
    *,
    kind: str,
    style: str,
    script: Path,
    audio: Path,
    dj_gender: str | None = None,
) -> None:
    item = {
        "id": f"{kind}/{style}/{script.name}",
        "kind": kind,
        "style": style,
        "script": str(script.relative_to(ROOT)),
        "audio": str(audio.relative_to(ROOT)),
        "text": script.read_text().strip(),
        "bytes": audio.stat().st_size if audio.is_file() else 0,
    }
    if dj_gender:
        item["dj_gender"] = dj_gender
    manifest["items"].append(item)


def batch_music3(
    kind: str,
    style: str,
    *,
    manifest: dict,
    skip_existing: bool,
    female: bool = False,
) -> None:
    scripts = sorted((SCRIPTS / kind).glob("*.txt"))[:10]
    if len(scripts) < 10:
        raise RuntimeError(f"need 10 {kind} scripts, found {len(scripts)}")
    seed_base = SEED_BASE[(kind, style)]
    out_dir = AUDIO / kind / style
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, script in enumerate(scripts):
        out = out_dir / f"{script.stem}.wav"
        if skip_existing and out.is_file() and manifest_has(manifest, out):
            print(f"skip existing {out.relative_to(ROOT)}", flush=True)
            continue
        print(f"\n=== {kind}/{style} {script.name} -> {out.name} ===", flush=True)
        music3_generate(script, out, seed_base + i, kind=kind, style=style, female=female)
        play(out)
        # replace manifest entry if regenerating
        rel = str(out.relative_to(ROOT))
        manifest["items"] = [x for x in manifest["items"] if x.get("audio") != rel]
        add_item(manifest, kind=kind, style=style, script=script, audio=out)
        save_manifest(manifest)


def batch_dj_music3(*, manifest: dict, skip_existing: bool, reshuffle_genders: bool = False) -> None:
    genders = load_dj_genders(reshuffle=reshuffle_genders)
    scripts = sorted((SCRIPTS / "dj-chatter").glob("*.txt"))
    seed_base = SEED_BASE[("dj-chatter", "voice")]
    out_dir = AUDIO / "dj-chatter"
    backup = out_dir / "piper-backup"
    out_dir.mkdir(parents=True, exist_ok=True)
    backup.mkdir(parents=True, exist_ok=True)
    for i, script in enumerate(scripts):
        gender = genders.get(script.stem) or random.choice(DJ_GENDER_CHOICES)
        out = out_dir / f"{script.stem}.wav"
        if skip_existing and out.is_file() and manifest_has(manifest, out):
            print(f"skip existing {out.relative_to(ROOT)}", flush=True)
            continue
        # preserve piper take once before music3 overwrite
        piper_copy = backup / f"{script.stem}.piper.wav"
        if out.is_file() and not piper_copy.is_file():
            shutil.copy2(out, piper_copy)
        print(f"\n=== dj-chatter/{gender} {script.name} -> {out.name} ===", flush=True)
        music3_generate(
            script,
            out,
            seed_base + i,
            kind="dj-chatter",
            style="voice",
            dj_gender=gender,
        )
        play(out)
        rel = str(out.relative_to(ROOT))
        manifest["items"] = [x for x in manifest["items"] if x.get("audio") != rel]
        add_item(
            manifest,
            kind="dj-chatter",
            style=f"voice-{gender}",
            script=script,
            audio=out,
            dj_gender=gender,
        )
        save_manifest(manifest)


def batch_piper(*, manifest: dict, skip_existing: bool) -> None:
    scripts = sorted((SCRIPTS / "dj-chatter").glob("*.txt"))
    out_dir = AUDIO / "dj-chatter"
    out_dir.mkdir(parents=True, exist_ok=True)
    for script in scripts:
        out = out_dir / f"{script.stem}.wav"
        if skip_existing and out.is_file():
            if not manifest_has(manifest, out):
                add_item(manifest, kind="dj-chatter", style="piper", script=script, audio=out)
                save_manifest(manifest)
            print(f"skip existing {out.relative_to(ROOT)}", flush=True)
            continue
        print(f"\n=== dj-chatter {script.name} -> {out.name} ===", flush=True)
        piper_generate(script, out)
        play(out)
        rel = str(out.relative_to(ROOT))
        manifest["items"] = [x for x in manifest["items"] if x.get("audio") != rel]
        add_item(manifest, kind="dj-chatter", style="piper", script=script, audio=out)
        save_manifest(manifest)


def rebuild_manifest_from_disk() -> dict:
    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(), "items": []}
    for kind in ("ads", "station-id"):
        for style in ("voice", "jingle"):
            script_dir = SCRIPTS / kind
            audio_dir = AUDIO / kind / style
            if not audio_dir.is_dir():
                continue
            for wav in sorted(audio_dir.glob("*.wav")):
                script = script_dir / f"{wav.stem}.txt"
                if script.is_file():
                    add_item(manifest, kind=kind, style=style, script=script, audio=wav)
    dj_dir = AUDIO / "dj-chatter"
    genders = {}
    if DJ_GENDERS_FILE.is_file():
        genders = json.loads(DJ_GENDERS_FILE.read_text()).get("genders") or {}
    if dj_dir.is_dir():
        for wav in sorted(dj_dir.glob("*.wav")):
            if wav.parent.name == "piper-backup":
                continue
            script = SCRIPTS / "dj-chatter" / f"{wav.stem}.txt"
            if script.is_file():
                g = genders.get(wav.stem, "music3")
                add_item(
                    manifest,
                    kind="dj-chatter",
                    style=f"voice-{g}" if g in DJ_GENDER_CHOICES else "voice",
                    script=script,
                    audio=wav,
                    dj_gender=g if g in DJ_GENDER_CHOICES else None,
                )
    save_manifest(manifest)
    return manifest


def main() -> int:
    argv = sys.argv[1:]
    mode = argv[0] if argv and not argv[0].startswith("-") else "music3-both"
    skip_existing = "--force" not in argv
    female = "--female" in argv or mode == "music3-remaining-female"

    reshuffle_genders = "--reshuffle-genders" in argv

    manifest = rebuild_manifest_from_disk()

    if mode in ("piper",):
        subprocess.run(warm_cmd("stop"), check=False)
        batch_piper(manifest=manifest, skip_existing=skip_existing)

    if mode in ("dj-music3",):
        run(warm_cmd("start"))
        batch_dj_music3(
            manifest=manifest,
            skip_existing=skip_existing,
            reshuffle_genders=reshuffle_genders,
        )

    music3_batches = {
        "music3": [
            ("station-id", "voice"),
            ("station-id", "jingle"),
            ("ads", "voice"),
            ("ads", "jingle"),
        ],
        "music3-both": [
            ("station-id", "voice"),
            ("station-id", "jingle"),
            ("ads", "voice"),
            ("ads", "jingle"),
        ],
        "music3-voice": [("station-id", "voice"), ("ads", "voice")],
        "music3-jingle": [("station-id", "jingle"), ("ads", "jingle")],
        "music3-remaining-female": [
            ("station-id", "jingle"),
            ("ads", "voice"),
            ("ads", "jingle"),
        ],
        "all": [
            ("station-id", "voice"),
            ("station-id", "jingle"),
            ("ads", "voice"),
            ("ads", "jingle"),
        ],
    }

    if mode in music3_batches:
        run(warm_cmd("start"))
        for kind, style in music3_batches[mode]:
            batch_music3(
                kind,
                style,
                manifest=manifest,
                skip_existing=skip_existing,
                female=female,
            )

    print(f"\nDone. Manifest: {MANIFEST} ({len(manifest['items'])} items)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
