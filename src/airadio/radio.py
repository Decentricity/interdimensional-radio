"""AI radio loop — generate songs, fill gaps with interstitials."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import random
import secrets
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from airadio import lyricist, music3, song_title
from airadio.paths import (
    ensure_user_layout,
    interstitials_audio_dir,
    library_dir,
    prompts_dir,
    staging_dir,
    user_home,
)
from airadio.storage import atomic_write_json

SONG_DURATION = 120
TAIL_FADE_MAX = 2.0
INTERSTITIAL_FADE_MAX = 2.0
MIN_LIBRARY_S = 30.0
INTERSTITIAL_FILL_MAX_S = 40.0
CROSSFADE_S = 2.5
GENERATION_MAX_ATTEMPTS = 3
GENERATION_RETRY_DELAYS_S = (5.0, 15.0)
DEFAULT_STAGING_KEEP = 20

_catalog_lock = threading.Lock()
_play_lock = threading.Lock()
_play_proc: subprocess.Popen[bytes] | None = None
_radio_lock_handle = None


class Config:
    def __init__(self, home: Path | None = None) -> None:
        self.home = ensure_user_layout(home)
        self.library = library_dir(self.home)
        self.quarantine = self.library / "quarantine"
        self.staging = staging_dir(self.home)
        self.lock_file = self.staging / "radio.lock"
        self.interstitials = interstitials_audio_dir(self.home)
        self.catalog = self.library / "catalog.json"
        self.playback = self.staging / "playback"
        self.caption = prompts_dir() / "normie-control.caption.txt"
        self.instrumental_caption = prompts_dir() / "normie-control.caption.instrumental.txt"
        self.instrumental_lyrics = (
            prompts_dir() / "normie-control.lyrics.instrumental.template.txt"
        )
        self.lyrics_grammar = lyricist.grammar_path()


class GenerationError(RuntimeError):
    def __init__(
        self,
        seed: int,
        attempts: int,
        cause: BaseException,
        *,
        stage: str = "generation",
    ) -> None:
        attempt_text = f" after {attempts} attempts" if attempts else ""
        super().__init__(f"song {stage} failed{attempt_text} (seed {seed}): {cause}")
        self.seed = seed
        self.attempts = attempts
        self.cause = cause


def missing_runtime_tools() -> list[str]:
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if not shutil.which("pw-play") and not shutil.which("aplay"):
        missing.append("pw-play or aplay")
    return missing


def log(msg: str) -> None:
    print(msg, flush=True)


def run_cmd(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    log("+ " + " ".join(cmd))
    return subprocess.run(cmd, check=True, **kw)


def duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        text=True,
    ).strip()
    return float(out)


def tail_fade(path: Path, out: Path, fade_max: float = TAIL_FADE_MAX) -> Path:
    dur = duration(path)
    fade = min(fade_max, max(0.35, dur * 0.12))
    start = max(0.0, dur - fade)
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-af",
            f"afade=t=out:st={start:.3f}:d={fade:.3f}",
            str(out),
        ]
    )
    return out


def crossfade(a: Path, b: Path, out: Path, fade_s: float = CROSSFADE_S) -> Path:
    """Overlap the end of *a* into the start of *b*."""
    fade = min(fade_s, max(0.05, duration(a) - 0.05), max(0.05, duration(b) - 0.05))
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(a),
            "-i",
            str(b),
            "-filter_complex",
            f"acrossfade=d={fade:.3f}:c1=tri:c2=tri",
            str(out),
        ]
    )
    return out


def stop_playback() -> None:
    global _play_proc
    with _play_lock:
        if _play_proc is not None and _play_proc.poll() is None:
            _play_proc.terminate()
            try:
                _play_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _play_proc.kill()
                _play_proc.wait(timeout=2)
        _play_proc = None


def stop_stray_radio_processes(cfg: Config) -> None:
    patterns = ("pw-play", "comfy", "airadio")
    staging = str(cfg.staging)
    for pattern in patterns:
        try:
            out = subprocess.check_output(["pgrep", "-af", pattern], text=True)
        except subprocess.CalledProcessError:
            continue
        for line in out.splitlines():
            if staging not in line:
                continue
            if "airadio" in line and "run" not in line and "music3" not in line:
                continue
            pid = int(line.split()[0])
            if pid == os.getpid():
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def acquire_radio_lock(cfg: Config) -> None:
    global _radio_lock_handle
    cfg.staging.mkdir(parents=True, exist_ok=True)
    # Opening with "w" would truncate the visible PID before discovering that
    # another process still owns the lock.
    handle = open(cfg.lock_file, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        log(f"another airadio instance is already running (see {cfg.lock_file})")
        raise SystemExit(1)
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _radio_lock_handle = handle


def release_radio_lock() -> None:
    global _radio_lock_handle
    if _radio_lock_handle is None:
        return
    fcntl.flock(_radio_lock_handle, fcntl.LOCK_UN)
    _radio_lock_handle.close()
    _radio_lock_handle = None


def play(path: Path, stop_if: Callable[[], bool] | None = None) -> bool:
    global _play_proc
    stop_playback()
    with _play_lock:
        if shutil.which("pw-play"):
            _play_proc = subprocess.Popen(["pw-play", str(path)])
        elif shutil.which("aplay"):
            _play_proc = subprocess.Popen(["aplay", "-q", str(path)])
        else:
            raise RuntimeError("no audio player found (need pw-play or aplay)")
        try:
            while _play_proc.poll() is None:
                if stop_if and stop_if():
                    return False
                time.sleep(0.25)
            return True
        finally:
            if _play_proc is not None and _play_proc.poll() is None:
                _play_proc.terminate()
                try:
                    _play_proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    _play_proc.kill()
                    _play_proc.wait(timeout=2)
            _play_proc = None


class SongGenerator:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._lock = threading.Lock()
        self._job: threading.Thread | None = None
        self._path: Path | None = None
        self._error: BaseException | None = None
        self._ready = threading.Event()
        self._seed = random.randint(1, 9999)
        self._started_at: float | None = None
        self._title: str | None = None

    def start(self) -> None:
        with self._lock:
            if self._job and self._job.is_alive():
                return
            self._ready.clear()
            self._path = None
            self._error = None
            self._title = None
            self._job = threading.Thread(target=self._run, daemon=True)
            self._job.start()

    def _run(self) -> None:
        cfg = self.cfg
        cfg.staging.mkdir(parents=True, exist_ok=True)
        out = cfg.staging / f"pending-{int(time.time())}.wav"
        seed = self._seed
        self._seed += 1
        self._started_at = time.time()
        title = song_title.random_title()
        instrumental = song_title.roll_instrumental()
        try:
            reservation = None if instrumental else lyricist.reserve_lyrics(cfg.home, title)
        except Exception as exc:  # noqa: BLE001
            self._error = GenerationError(seed, 0, exc, stage="preparation")
            log(f"could not reserve unique lyrics: {exc}")
            self._ready.set()
            return
        lyric_id = reservation.lyric_id if reservation is not None else None
        self._title = title
        kind = "instrumental" if instrumental else "vocal"
        log(f'generation started (seed {seed}, title "{title}", {kind})')
        prompt_dir = cfg.staging / "prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time() * 1000)
        caption_path = prompt_dir / f"caption-{stamp}.txt"
        lyrics_path = prompt_dir / f"lyrics-{stamp}.txt"
        caption_path.write_text(
            song_title.build_caption(title, instrumental=instrumental), encoding="utf-8"
        )
        lyrics = (
            song_title.build_lyrics(title, instrumental=True)
            if instrumental
            else reservation.text
        )
        lyrics_path.write_text(lyrics, encoding="utf-8")
        last_error: BaseException | None = None
        for attempt in range(1, GENERATION_MAX_ATTEMPTS + 1):
            out.unlink(missing_ok=True)
            try:
                music3.generate(
                    lyrics=lyrics_path,
                    caption=caption_path,
                    duration=SONG_DURATION,
                    seed=seed,
                    out=out,
                    play=False,
                )
                break
            except subprocess.CalledProcessError as exc:
                if out.is_file() and _valid_duration(out):
                    log(f"gen exited {exc.returncode} but output exists — using {out.name}")
                    break
                last_error = exc
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            if attempt < GENERATION_MAX_ATTEMPTS:
                delay = GENERATION_RETRY_DELAYS_S[attempt - 1]
                log(
                    f"generation attempt {attempt}/{GENERATION_MAX_ATTEMPTS} failed "
                    f"(seed {seed}): {last_error}; retrying in {delay:.0f}s"
                )
                time.sleep(delay)
        else:
            assert last_error is not None
            self._error = GenerationError(seed, GENERATION_MAX_ATTEMPTS, last_error)
            log(str(self._error))
            self._ready.set()
            return
        try:
            if not out.is_file():
                raise RuntimeError("generation produced no file")
            archived = archive_song(
                cfg,
                out,
                seed=seed,
                title=title,
                instrumental=instrumental,
                lyric_id=lyric_id,
                lyrics_hash=(reservation.sha256 if reservation is not None else None),
            )
            self._path = archived
            if archived.resolve() != out.resolve():
                out.unlink(missing_ok=True)
            cleanup_staging(cfg)
            elapsed = time.time() - (self._started_at or time.time())
            log(f'generation finished in {elapsed:.0f}s (seed {seed}, title "{title}")')
        except Exception as exc:  # noqa: BLE001
            self._error = GenerationError(seed, 0, exc, stage="finalization")
            log(str(self._error))
        finally:
            self._ready.set()

    def waiting_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.time() - self._started_at

    def ready(self) -> bool:
        return self._ready.is_set()

    def result(self) -> Path:
        self._ready.wait()
        if self._error:
            raise self._error
        assert self._path is not None
        return self._path


def _valid_duration(path: Path) -> bool:
    try:
        return duration(path) >= MIN_LIBRARY_S
    except (subprocess.CalledProcessError, ValueError, OSError):
        return False


def list_interstitials(cfg: Config) -> list[Path]:
    files = [p for p in cfg.interstitials.rglob("*.wav") if "piper-backup" not in p.parts]
    if not files:
        raise RuntimeError(f"no interstitials under {cfg.interstitials}")
    return files


def file_hash(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rebuilt_catalog(cfg: Config) -> dict:
    songs = []
    for path in sorted(cfg.library.glob("*.wav")):
        if is_quarantined(cfg, path) or not _valid_duration(path):
            continue
        songs.append(
            {
                "path": str(path.relative_to(cfg.home)),
                "saved_at": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
                "duration_s": round(duration(path), 3),
                "bytes": path.stat().st_size,
                "md5": file_hash(path),
                "recovered": True,
            }
        )
    return {"songs": songs}


def load_catalog(cfg: Config) -> dict:
    if not cfg.catalog.is_file():
        return {"songs": []}
    try:
        catalog = json.loads(cfg.catalog.read_text(encoding="utf-8"))
        if not isinstance(catalog, dict) or not isinstance(catalog.get("songs", []), list):
            raise ValueError("catalog root must contain a songs list")
        return catalog
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = cfg.catalog.with_name(f"catalog.corrupt-{stamp}.json")
        shutil.copy2(cfg.catalog, backup)
        catalog = _rebuilt_catalog(cfg)
        atomic_write_json(cfg.catalog, catalog)
        log(f"recovered invalid catalog ({exc}); original saved as {backup.name}")
        return catalog


def find_library_song(cfg: Config, md5: str) -> Path | None:
    for entry in load_catalog(cfg).get("songs", []):
        if entry.get("md5") != md5:
            continue
        path = cfg.home / entry["path"]
        if path.is_file() and cfg.quarantine not in path.parents:
            return path
    return None


def is_quarantined(cfg: Config, path: Path) -> bool:
    try:
        path.resolve().relative_to(cfg.quarantine.resolve())
        return True
    except ValueError:
        return False


def ensure_catalog_hashes(cfg: Config) -> None:
    with _catalog_lock:
        catalog = load_catalog(cfg)
        changed = False
        for entry in catalog.get("songs", []):
            if entry.get("md5"):
                continue
            path = cfg.home / entry["path"]
            if not path.is_file():
                continue
            entry["md5"] = file_hash(path)
            changed = True
        if changed:
            atomic_write_json(cfg.catalog, catalog)


def archive_song(
    cfg: Config,
    src: Path,
    seed: int | None = None,
    title: str | None = None,
    *,
    instrumental: bool | None = None,
    lyric_id: int | None = None,
    lyrics_hash: str | None = None,
) -> Path:
    cfg.library.mkdir(parents=True, exist_ok=True)
    md5 = file_hash(src)
    with _catalog_lock:
        existing = find_library_song(cfg, md5)
        if existing is not None:
            log(f"already saved {existing.relative_to(cfg.home)}")
            return existing
        if title is not None and seed is not None:
            dest = cfg.library / song_title.song_filename(title, seed, lyric_id)
        elif title is not None:
            dest = cfg.library / f"{song_title.title_slug(title)}.wav"
        else:
            dest = cfg.library / f"song-{datetime.now().strftime('%Y%m%d-%H%M%S')}.wav"
        if dest.exists():
            stem = dest.stem
            suffix = 2
            while dest.exists():
                dest = dest.with_name(f"{stem}-{suffix}.wav")
                suffix += 1
        shutil.copy2(src, dest)
        entry = {
            "path": str(dest.relative_to(cfg.home)),
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": round(duration(dest), 3),
            "bytes": dest.stat().st_size,
            "md5": md5,
        }
        if seed is not None:
            entry["seed"] = seed
        if title is not None:
            entry["title"] = title
        if instrumental is not None:
            entry["instrumental"] = instrumental
        if lyric_id is not None:
            entry["lyric_id"] = lyric_id
        if lyrics_hash is not None:
            entry["lyrics_sha256"] = lyrics_hash
        catalog = load_catalog(cfg)
        catalog.setdefault("songs", []).append(entry)
        atomic_write_json(cfg.catalog, catalog)
    log(f"saved {dest.relative_to(cfg.home)}")
    return dest


def import_staging_songs(cfg: Config) -> int:
    imported = 0
    for src in sorted(cfg.staging.glob("pending-*.wav")):
        if not _valid_duration(src):
            continue
        if find_library_song(cfg, file_hash(src)) is None:
            archive_song(cfg, src)
            imported += 1
        src.unlink(missing_ok=True)
    return imported


def _retention_count() -> int:
    raw = os.environ.get("AIRADIO_STAGING_KEEP", str(DEFAULT_STAGING_KEEP))
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_STAGING_KEEP


def _prune_old_files(paths: list[Path], keep: int) -> None:
    ordered = sorted((p for p in paths if p.is_file()), key=lambda p: p.stat().st_mtime)
    for path in ordered[: max(0, len(ordered) - keep)]:
        path.unlink(missing_ok=True)


def cleanup_staging(cfg: Config) -> None:
    """Bound diagnostic prompts, failed generations, and playback derivatives."""
    keep = _retention_count()
    _prune_old_files(list(cfg.staging.glob("pending-*.wav")), keep)
    prompt_dir = cfg.staging / "prompts"
    _prune_old_files(list(prompt_dir.glob("caption-*.txt")), keep)
    _prune_old_files(list(prompt_dir.glob("lyrics-*.txt")), keep)
    _prune_old_files(list(cfg.playback.glob("*.wav")), keep)


def play_song(path: Path, tmp: Path) -> None:
    play(tail_fade(path, tmp / "song-play.wav"))


def list_library_songs(cfg: Config) -> list[Path]:
    if not cfg.library.is_dir():
        return []
    songs = []
    for path in cfg.library.glob("*.wav"):
        if is_quarantined(cfg, path):
            continue
        if _valid_duration(path):
            songs.append(path)
    return sorted(songs)


def pick_library_song(cfg: Config, exclude: Path | None = None) -> Path | None:
    library = list_library_songs(cfg)
    if exclude is not None and len(library) > 1:
        library = [p for p in library if p.resolve() != exclude.resolve()]
    if not library:
        return None
    return secrets.choice(library)


def play_song_pipeline(song: Path, gen: SongGenerator, tmp: Path) -> None:
    gen.start()
    log("generating next song while current plays")
    play_song(song, tmp)


def bootstrap_first_song(gen: SongGenerator, cfg: Config, tmp: Path) -> tuple[Path, bool]:
    gen.start()
    log("generating next song while current plays")
    warmup: Path | None = None
    pick = pick_library_song(cfg)
    if pick is not None:
        log(f"warm-up playback: {pick.relative_to(cfg.home)} (first song generating)")
        warmup = tail_fade(pick, tmp / f"warmup-{int(time.time() * 1000)}.wav")
        play(warmup)
    else:
        log("no library songs yet — waiting for first generation…")
    if not gen.ready():
        log("first song still generating — fill until ready")
        return transition_with_fill(gen, cfg, tmp)
    nxt = gen.result()
    if warmup is not None:
        play_song_pipeline(nxt, gen, tmp)
        if gen.ready():
            log("next song ready immediately after warm-up")
            return gen.result(), True
        return transition_with_fill(gen, cfg, tmp)
    return nxt, False


def play_bridge_into_song(cfg: Config, song: Path, gen: SongGenerator, tmp: Path) -> None:
    """Play a fresh interstitial crossfaded into *song*, generating the next song meanwhile."""
    gen.start()
    log("generating next song while bridge + song play")
    pick = random.choice(list_interstitials(cfg))
    rel = pick.relative_to(cfg.interstitials)
    log(f"bridge interstitial {rel} → song")
    stamp = int(time.time() * 1000)
    # Don't pre-fade the bridge clip — acrossfade handles the handoff into the song.
    song_faded = tail_fade(song, tmp / f"song-bridged-{stamp}.wav")
    bridged = crossfade(pick, song_faded, tmp / f"bridge-{stamp}.wav")
    play(bridged)


def play_library_song_fill(gen: SongGenerator, cfg: Config, tmp: Path) -> Path | None:
    pick = pick_library_song(cfg)
    if pick is None:
        return None
    log(f"library track: {pick.relative_to(cfg.home)}")
    faded = tail_fade(pick, tmp / f"library-fill-{int(time.time() * 1000)}.wav")
    # Always finish the library track; bridge interstitial comes after.
    play(faded)
    return faded


def play_interstitial_clip(gen: SongGenerator, cfg: Config, tmp: Path) -> Path:
    pick = random.choice(list_interstitials(cfg))
    rel = pick.relative_to(cfg.interstitials)
    log(f"interstitial {rel}")
    faded = tail_fade(pick, tmp / f"inter-{int(time.time() * 1000)}.wav", INTERSTITIAL_FADE_MAX)
    # Always finish the interstitial; bridge into the new song happens after.
    play(faded)
    return faded


def play_interstitial_phase(gen: SongGenerator, cfg: Config, tmp: Path) -> Path | None:
    last: Path | None = None
    phase_start = time.time()
    while not gen.ready() and (time.time() - phase_start) < INTERSTITIAL_FILL_MAX_S:
        last = play_interstitial_clip(gen, cfg, tmp)
        if gen.ready():
            break
    return last


def transition_with_fill(gen: SongGenerator, cfg: Config, tmp: Path) -> tuple[Path, bool]:
    while True:
        log(f"waiting for song ({gen.waiting_seconds():.0f}s elapsed)…")
        _last, nxt = play_wait_session(gen, cfg, tmp)
        # Current fill clip has finished. Bridge with a fresh interstitial.
        play_bridge_into_song(cfg, nxt, gen, tmp)
        if gen.ready():
            log("next song ready after fill")
            return gen.result(), True
        log("still generating after song — more fill")


def play_wait_session(gen: SongGenerator, cfg: Config, tmp: Path) -> tuple[Path | None, Path]:
    last: Path | None = None
    while not gen.ready():
        last = play_interstitial_phase(gen, cfg, tmp)
        if gen.ready():
            break
        log(
            f"interstitials hit {INTERSTITIAL_FILL_MAX_S:.0f}s — "
            "playing a full library track while generating"
        )
        library_last = play_library_song_fill(gen, cfg, tmp)
        if library_last is not None:
            last = library_last
        if gen.ready():
            break
    return last, gen.result()


def run(
    home: Path | None = None,
    *,
    verbose: bool = False,
    quiet: bool = False,
    skip_setup: bool = False,
) -> int:
    from airadio import setup

    cfg = Config(home)
    # ComfyUI + Music 3 must be reachable before setup or the radio loop.
    if not music3.require_ready():
        return 1
    missing_tools = missing_runtime_tools()
    if missing_tools:
        log("missing required runtime tools: " + ", ".join(missing_tools))
        return 1
    if not skip_setup:
        if setup.is_ready(cfg.home):
            if verbose:
                log(f"setup skipped — already ready ({setup.readiness_summary(cfg.home)})")
        elif not setup.run_first_time_setup(cfg.home, verbose=verbose, quiet=quiet):
            return 0
    required_generation_data = (
        cfg.caption,
        cfg.instrumental_caption,
        cfg.instrumental_lyrics,
        cfg.lyrics_grammar,
    )
    missing = [path for path in required_generation_data if not path.is_file()]
    if missing:
        log("missing generation data: " + ", ".join(str(path) for path in missing))
        return 1
    acquire_radio_lock(cfg)
    try:
        # Only the lock owner may clean up stale processes from an earlier run.
        stop_stray_radio_processes(cfg)
        stop_playback()
        cfg.playback.mkdir(parents=True, exist_ok=True)
        ensure_catalog_hashes(cfg)
        imported = import_staging_songs(cfg)
        if imported:
            log(f"imported {imported} unstaged song(s) into library")
        cleanup_staging(cfg)
        gen = SongGenerator(cfg)
        song, skip_play = bootstrap_first_song(gen, cfg, cfg.playback)
        while True:
            if not skip_play:
                play_song_pipeline(song, gen, cfg.playback)
            else:
                skip_play = False
            if gen.ready():
                song = gen.result()
                log("next song ready — no wait session")
            else:
                log("next song still generating — fill until ready")
                song, skip_play = transition_with_fill(gen, cfg, cfg.playback)
    except KeyboardInterrupt:
        log("stopped")
        return 130
    except GenerationError as exc:
        log(str(exc))
        return 1
    finally:
        stop_playback()
        release_radio_lock()


def main() -> int:
    return run()
