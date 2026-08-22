"""First-run setup: check assets, wizard, interstitial generation."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from airadio import interstitial_gen, music3
from airadio.paths import bundled_interstitials_dir, ensure_user_layout, user_home

MIN_LIBRARY_S = 30.0


@dataclass
class SetupConfig:
    radio_name: str
    call_letters: str
    ad_count: int
    station_id_count: int


def config_path(home: Path) -> Path:
    return home / "config.json"


def load_config(home: Path) -> dict | None:
    path = config_path(home)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(home: Path, cfg: SetupConfig) -> None:
    config_path(home).write_text(
        json.dumps(
            {
                "radio_name": cfg.radio_name,
                "call_letters": cfg.call_letters,
                "ad_count": cfg.ad_count,
                "station_id_count": cfg.station_id_count,
                "setup_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def call_letters_from_name(name: str) -> str:
    words = re.findall(r"[A-Za-z]+", name)
    if not words:
        return "AIR"
    letters = "".join(word[0].upper() for word in words)
    return letters[:4] if letters else "AIR"


def normalize_radio_name(name: str) -> str:
    """Ensure the station name includes the word 'radio' for clearer TTS prompts."""
    cleaned = name.strip()
    if not cleaned:
        return "Radio"
    if re.search(r"\bradio\b", cleaned, re.IGNORECASE):
        return cleaned
    return f"{cleaned} Radio"


def _wav_duration(path: Path) -> bool:
    try:
        out = __import__("subprocess").check_output(
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
        return float(out) >= MIN_LIBRARY_S
    except (ValueError, OSError, __import__("subprocess").CalledProcessError):
        return False


def count_interstitials(home: Path, kind: str) -> int:
    root = home / "interstitials" / "audio" / kind
    if not root.is_dir():
        return 0
    return sum(1 for _ in root.rglob("*.wav"))


def count_library_songs(home: Path) -> int:
    library = home / "library"
    if not library.is_dir():
        return 0
    n = 0
    for path in library.glob("*.wav"):
        if _wav_duration(path):
            n += 1
    return n


def is_ready(home: Path | None = None) -> bool:
    """True when at least one ad, station ID, and library song exist."""
    root = home or user_home()
    return (
        count_interstitials(root, "ads") >= 1
        and count_interstitials(root, "station-id") >= 1
        and count_library_songs(root) >= 1
    )


def readiness_summary(home: Path) -> str:
    ads = count_interstitials(home, "ads")
    ids = count_interstitials(home, "station-id")
    songs = count_library_songs(home)
    return f"ads={ads}, station IDs={ids}, library songs={songs}"


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            value = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            print(flush=True)
            sys.exit(1)
        if not value and default is not None:
            return default
        if value:
            return value
        print("Please enter a value.", flush=True)


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        try:
            value = input(f"{prompt} [{hint}]: ").strip().lower()
        except EOFError:
            print(flush=True)
            sys.exit(1)
        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print("Please answer Y or N.", flush=True)


def _ask_count(prompt: str, default: int = 3) -> int:
    while True:
        raw = _ask(prompt, str(default))
        try:
            n = int(raw)
        except ValueError:
            print("Enter a number between 1 and 10.", flush=True)
            continue
        if 1 <= n <= 10:
            return n
        print("Enter a number between 1 and 10.", flush=True)


def fill_template(text: str, cfg: SetupConfig) -> str:
    return text.format(
        radio_name=cfg.radio_name,
        call_letters=cfg.call_letters,
    )


def prepare_scripts(home: Path, setup: SetupConfig) -> list[tuple[str, Path, Path]]:
    """Write madlib scripts; return (kind, script_path, audio_out_path) jobs."""
    bundled = bundled_interstitials_dir() / "scripts"
    jobs: list[tuple[str, Path, Path]] = []

    ads_src = sorted((bundled / "ads").glob("*.txt"))[: setup.ad_count]
    ids_src = sorted((bundled / "station-id").glob("*.txt"))[: setup.station_id_count]

    for kind, sources, style in (
        ("ads", ads_src, "voice"),
        ("station-id", ids_src, "voice"),
    ):
        script_dir = home / "interstitials" / "scripts" / kind
        audio_dir = home / "interstitials" / "audio" / kind / style
        script_dir.mkdir(parents=True, exist_ok=True)
        audio_dir.mkdir(parents=True, exist_ok=True)
        for src in sources:
            text = src.read_text(encoding="utf-8").strip()
            if kind == "station-id":
                text = fill_template(text, setup)
            script_path = script_dir / src.name
            script_path.write_text(text + "\n", encoding="utf-8")
            out_wav = audio_dir / f"{src.stem}.wav"
            jobs.append((kind, script_path, out_wav))
    return jobs


def render_progress(current: int, total: int, label: str, *, quiet: bool) -> None:
    if quiet:
        return
    width = 36
    filled = int(width * current / total) if total else width
    bar = "█" * filled + "░" * (width - filled)
    print(f"\r[{bar}] {current}/{total} {label[:40]:<40}", end="", flush=True)
    if current >= total:
        print(flush=True)


def generate_interstitials(
    home: Path,
    setup: SetupConfig,
    *,
    verbose: bool = False,
    quiet: bool = False,
) -> None:
    jobs = prepare_scripts(home, setup)
    total = len(jobs)
    if not quiet:
        print(f"\nGenerating {total} interstitial clip(s)…", flush=True)
    if not music3.require_ready():
        raise RuntimeError("ComfyUI + MiniMax Music 3 is not reachable")
    for i, (kind, script, out_wav) in enumerate(jobs, start=1):
        label = f"{kind}/{out_wav.name}"
        render_progress(i - 1, total, label, quiet=quiet)
        if verbose or not quiet:
            print(f"\n=== {label} ===", flush=True)
        seed = interstitial_gen.SEED_BASE[(kind, "voice")] + i
        interstitial_gen.generate_voice_clip(
            script, out_wav, kind=kind, seed=seed, verbose=verbose
        )
        if verbose or not quiet:
            print(f"Playing {out_wav.name}…", flush=True)
        interstitial_gen.play_audio(out_wav)
        render_progress(i, total, label, quiet=quiet)
    save_config(home, setup)
    if not quiet:
        print("Interstitial generation complete.", flush=True)


def run_first_time_setup(
    home: Path | None = None,
    *,
    verbose: bool = False,
    quiet: bool = False,
    force: bool = False,
) -> bool:
    """
    Interactive setup when assets are missing.
    Returns True if the radio loop should start afterward.
    """
    root = ensure_user_layout(home)

    if not force and is_ready(root):
        if verbose:
            print(f"Setup skipped — already ready ({readiness_summary(root)})", flush=True)
        return True

    # Don't ask wizard questions if generation cannot run yet.
    if not music3.require_ready():
        return False

    if not quiet:
        print("\nWelcome to airadio!", flush=True)
        print(
            f"Your station folder ({root}) needs interstitials before the radio can fill gaps.\n",
            flush=True,
        )

    raw_name = _ask("What is the name of your radio?", "Interdimensional Radio")
    radio_name = normalize_radio_name(raw_name)
    if not quiet and radio_name != raw_name.strip():
        print(f"Station name: {radio_name}", flush=True)
    ad_count = _ask_count("How many ads should we generate? (max 10)", 3)
    station_count = _ask_count("How many station identification segments? (max 10)", 3)
    setup = SetupConfig(
        radio_name=radio_name,
        call_letters=call_letters_from_name(radio_name),
        ad_count=ad_count,
        station_id_count=station_count,
    )

    total_clips = ad_count + station_count
    print(
        f"\n{setup.radio_name} ({setup.call_letters}) — "
        f"{ad_count} ad(s) + {station_count} station ID(s) = {total_clips} clip(s) to generate.",
        flush=True,
    )
    if not _ask_yes_no("Generate interstitials now?", default=True):
        print("Setup cancelled.", flush=True)
        return False

    if verbose:
        print("Verbose mode on.", flush=True)
    if quiet:
        print("Quiet mode on (progress bar only).", flush=True)

    generate_interstitials(root, setup, verbose=verbose, quiet=quiet)

    if count_library_songs(root) < 1:
        print(
            "\nNote: no library songs yet — the first run will wait for the first generation.",
            flush=True,
        )

    return _ask_yes_no("\nStart the radio now?", default=True)
