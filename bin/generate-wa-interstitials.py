#!/usr/bin/env python3
"""Generate 110 WhatsApp interstitial scripts into AIRADIO_HOME (no PyPI edits).

Uses the same Music3 path airadio uses (Comfy @ :8188 + caption/lyrics), randomly
picking voice-only vs jingle per clip. Plays each WAV as it finishes.
Does not touch bundled madlib station-id templates.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

AIRADIO_HOME = Path.home() / ".local" / "share" / "airadio"
INBOX = Path("/home/decentricity/music/interstitials/inbox/interstitials-from-whatsapp.txt")
PROMPTS = Path("/home/decentricity/music/interstitials/prompts")
COMFY_ROOT = Path.home() / ".local" / "share" / "comfy-music3"
COMFY_PY = COMFY_ROOT / ".venv" / "bin" / "python"
LOCK = Path.home() / ".local" / "share" / "minimax-music3" / "gpu.lock"
SEED_BASE = 2200

CAPTIONS = {
    ("ads", "voice"): PROMPTS / "voice-only.caption.txt",
    ("ads", "jingle"): PROMPTS / "radio-ad.caption.txt",
    ("station-id", "voice"): PROMPTS / "voice-only.caption.txt",
    ("station-id", "jingle"): PROMPTS / "station-id.caption.txt",
}

GENDERS = ("male", "female", "alien")

VOCAL_BY_GENDER = {
    "male": (
        "Vocal Details\n"
        "Male announcer ONLY — clearly adult male human voice, baritone/tenor. "
        "ABSOLUTELY NO FEMALE VOICE. Natural speech, not sung. "
        "Speak ONLY the exact words in the lyrics — no added filler or sign-offs."
    ),
    "female": (
        "Vocal Details\n"
        "Female announcer ONLY — clearly adult female human voice, mezzo-soprano. "
        "ABSOLUTELY NO MALE VOICE. Natural speech, not sung. "
        "Speak ONLY the exact words in the lyrics — no added filler or sign-offs."
    ),
    "alien": (
        "Vocal Details\n"
        "Alien announcer ONLY — otherworldly non-human voice, intelligible English, "
        "uncanny timbre. Neither male nor female human. Natural speech, not sung. "
        "Speak ONLY the exact words in the lyrics — no added filler or sign-offs."
    ),
}


def caption_with_gender(base: Path, gender: str, dest: Path) -> Path:
    text = base.read_text(encoding="utf-8")
    block = VOCAL_BY_GENDER[gender]
    if re.search(r"(?ms)^Vocal Details\n.*?(?=\nArrangement\b|\Z)", text):
        text = re.sub(
            r"(?ms)^Vocal Details\n.*?(?=\nArrangement\b|\Z)",
            block + "\n",
            text,
            count=1,
        )
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    dest.write_text(text, encoding="utf-8")
    return dest


def parse_items(text: str) -> list[tuple[int, str, str]]:
    items: list[tuple[int, str, str]] = []
    for m in re.finditer(r"(?m)^\s*(\d+)\.\s*(Station ID|Ad)\s*$", text):
        kind = "station-id" if m.group(2) == "Station ID" else "ads"
        num = int(m.group(1))
        start = m.end()
        nxt = re.search(r"(?m)^\s*\d+\.\s*(?:Station ID|Ad)\s*$", text[start:])
        chunk = text[start : start + (nxt.start() if nxt else len(text) - start)]
        qm = re.search(r"[“\"](.+?)[”\"]", chunk, re.S)
        if qm:
            body = qm.group(1)
        else:
            qm = re.search(r"[“\"](.+)", chunk, re.S)
            body = (qm.group(1) if qm else chunk).rstrip("”\"").strip()
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            items.append((num, kind, body))
    return items


def slugify(text: str, *, max_len: int = 36) -> str:
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:max_len].rstrip("-") or "clip")


def duration_for_text(text: str, *, kind: str, style: str) -> int:
    words = len(text.split())
    if kind == "ads":
        if style == "jingle":
            secs = max(7.0, min(9.5, words / 2.5 + 1.5))
        else:
            secs = max(8.0, min(10.0, words / 2.8 + 1.5))
    else:
        secs = max(5.0, min(12.0, words / 2.2 + 1.5))
    return max(5, int(round(secs)))


def play_audio(path: Path) -> None:
    for cmd in (["pw-play", str(path)], ["aplay", "-q", str(path)]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, check=False)
            return
    print(f"  (no player; skipped playback for {path.name})", flush=True)


def wait_comfy(timeout_s: float = 240.0) -> None:
    import urllib.request

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception:
            pass
        time.sleep(1.5)
    raise RuntimeError("ComfyUI did not become ready on :8188")


def ensure_comfy() -> subprocess.Popen | None:
    """Start ComfyUI if needed. Returns Popen if we started it, else None."""
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=2):
            print("ComfyUI already up on :8188", flush=True)
            return None
    except Exception:
        pass

    if not COMFY_PY.is_file():
        raise RuntimeError(f"ComfyUI python missing: {COMFY_PY}")

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    log = Path("/tmp/wa-interstitials-comfy.log")
    print("Starting ComfyUI…", flush=True)
    proc = subprocess.Popen(
        [str(COMFY_PY), "main.py", "--listen", "127.0.0.1", "--port", "8188", "--disable-auto-launch"],
        cwd=str(COMFY_ROOT),
        stdout=log.open("w"),
        stderr=subprocess.STDOUT,
    )
    try:
        wait_comfy()
    except Exception:
        proc.terminate()
        raise
    print(f"ComfyUI ready (pid {proc.pid}); log {log}", flush=True)
    return proc


def free_gpu_hint() -> None:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_gpu_memory",
                "--format=csv,noheader",
            ],
            text=True,
        ).strip()
    except Exception:
        return
    if out:
        print("GPU processes before gen:\n" + out, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260823)
    ap.add_argument("--limit", type=int, default=0, help="optional cap for testing")
    ap.add_argument("--from-num", type=int, default=1, help="start at this script number (inclusive)")
    ap.add_argument("--force", action="store_true", help="regenerate even if WAV exists")
    ap.add_argument("--no-play", action="store_true")
    ap.add_argument("--inbox", type=Path, default=INBOX)
    args = ap.parse_args()

    project_src = Path(__file__).resolve().parents[1] / "src"
    sys.path.insert(0, str(project_src))

    from airadio import interstitial_provenance, music3  # type: ignore

    text = args.inbox.read_text(encoding="utf-8")
    items = parse_items(text)
    if len(items) != 110:
        print(f"warning: expected 110 scripts, parsed {len(items)}", flush=True)
    if args.from_num > 1:
        items = [it for it in items if it[0] >= args.from_num]
    if args.limit:
        items = items[: args.limit]

    rng = random.Random(args.seed)
    free_gpu_hint()
    # Unload ollama model if present (best-effort; no sudo).
    try:
        subprocess.run(["ollama", "stop", "qwen3:8b"], check=False, capture_output=True)
        time.sleep(2)
    except FileNotFoundError:
        pass

    comfy_proc = ensure_comfy()
    if not music3.ready():
        print(music3.unreachable_message(), end="", flush=True)
        if comfy_proc:
            comfy_proc.terminate()
        return 1

    home = AIRADIO_HOME
    work = home / "interstitials" / ".wa-work"
    work.mkdir(parents=True, exist_ok=True)
    log_path = home / "interstitials" / "wa-batch-log.jsonl"
    manifest: list[dict] = []

    print(f"Generating {len(items)} interstitials into {home / 'interstitials'}", flush=True)
    try:
        for i, (num, kind, body) in enumerate(items, start=1):
            style = rng.choice(("voice", "jingle"))
            # Prefer female for the back half of the batch (user request).
            gender = "female" if num > 51 else rng.choice(GENDERS)
            base_caption = CAPTIONS[(kind, style)]
            slug = f"wa-{num:03d}-{gender}-{slugify(body)}"
            script_dir = home / "interstitials" / "scripts" / kind
            audio_dir = home / "interstitials" / "audio" / kind / style
            script_dir.mkdir(parents=True, exist_ok=True)
            audio_dir.mkdir(parents=True, exist_ok=True)
            script_path = script_dir / f"{slug}.txt"
            out_wav = audio_dir / f"{slug}.wav"
            script_path.write_text(body + "\n", encoding="utf-8")

            provenance_path = interstitial_provenance.provenance_sidecar_path(out_wav)
            if out_wav.is_file() and provenance_path.is_file() and not args.force:
                print(
                    f"[{i}/{len(items)}] skip existing {kind}/{style}/{gender}/{out_wav.name}",
                    flush=True,
                )
                manifest.append(
                    {
                        "num": num,
                        "kind": kind,
                        "style": style,
                        "gender": gender,
                        "audio": str(out_wav.relative_to(home)),
                        "skipped": True,
                    }
                )
                continue

            dur = duration_for_text(body, kind=kind, style=style)
            seed = SEED_BASE + num
            lyrics = work / f"{slug}.lyrics.txt"
            lyrics.write_text(f"[verse]\n{body}\n", encoding="utf-8")
            caption = caption_with_gender(base_caption, gender, work / f"{slug}.caption.txt")

            print(
                f"\n[{i}/{len(items)}] {kind}/{style}/{gender}  {dur}s  seed={seed}\n"
                f"  {body[:90]}{'…' if len(body) > 90 else ''}",
                flush=True,
            )
            t0 = time.time()
            temporary = out_wav.parent / f".{out_wav.name}.{uuid.uuid4().hex}.tmp.wav"
            try:
                music3.generate(
                    lyrics=lyrics,
                    caption=caption,
                    duration=dur,
                    seed=seed,
                    out=temporary,
                    play=False,
                    verbose=True,
                )
                temporary.replace(out_wav)
                record = interstitial_provenance.record_generation(
                    home,
                    out_wav,
                    lyrics=lyrics.read_text(encoding="utf-8"),
                    kind=kind,
                    style=style,
                    backend="minimax-music3",
                    source_script=script_path,
                    caption=caption,
                    seed=seed,
                    duration_s=dur,
                    gender=gender,
                    extra={"whatsapp_item_number": num},
                )
            finally:
                temporary.unlink(missing_ok=True)
            wall = time.time() - t0
            print(f"  wrote {out_wav} ({wall:.1f}s)", flush=True)
            if not args.no_play:
                print(f"  playing {out_wav.name}…", flush=True)
                play_audio(out_wav)

            entry = {
                "num": num,
                "kind": kind,
                "style": style,
                "gender": gender,
                "duration_req": dur,
                "seed": seed,
                "script": str(script_path.relative_to(home)),
                "audio": str(out_wav.relative_to(home)),
                "wall_s": round(wall, 1),
                "text": body,
                "generation_id": record["generation_id"],
            }
            manifest.append(entry)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
    finally:
        summary = home / "interstitials" / "wa-batch-summary.json"
        summary.write_text(json.dumps({"count": len(manifest), "items": manifest}, indent=2) + "\n")
        print(f"\nSummary: {summary}", flush=True)
        # Leave Comfy running if we started it — user may want more gens.
        # Only note the pid.
        if comfy_proc is not None:
            print(f"ComfyUI still running (pid {comfy_proc.pid}); stop manually when done.", flush=True)

    done = sum(1 for e in manifest if not e.get("skipped"))
    skipped = sum(1 for e in manifest if e.get("skipped"))
    print(f"Done. generated={done} skipped={skipped} total={len(manifest)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
