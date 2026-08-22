"""Warm ComfyUI server and MiniMax Music 3 generation."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from airadio import workflow
from airadio.paths import user_home

MINIMAX_ROOT = Path(
    os.environ.get("MINIMAX_ROOT", Path.home() / ".local/share/minimax-music3")
).expanduser()
COMFY_ROOT = Path(
    os.environ.get("COMFY_ROOT", Path.home() / ".local/share/comfy-music3")
).expanduser()
COMFY_BIN = Path(
    os.environ.get("COMFY_BIN", MINIMAX_ROOT / "venv/bin/comfy")
).expanduser()
PORT = int(os.environ.get("AIRADIO_COMFY_PORT", "8188"))
HOST = os.environ.get("AIRADIO_COMFY_HOST", "127.0.0.1")
LOCK = MINIMAX_ROOT / "gpu.lock"


def _home() -> Path:
    return user_home()


def _pid_file() -> Path:
    return _home() / ".comfy-warm.pid"


def _lock_pid_file() -> Path:
    return _home() / ".comfy-warm-lock.pid"


def _log_file() -> Path:
    return _home() / ".comfy-warm.log"


def server_up() -> bool:
    try:
        subprocess.run(
            ["curl", "-sf", f"http://{HOST}:{PORT}/system_stats"],
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def start_server() -> None:
    home = _home()
    home.mkdir(parents=True, exist_ok=True)
    pid_file = _pid_file()
    if server_up():
        print(f"ComfyUI already up on {HOST}:{PORT}")
    else:
        if pid_file.is_file():
            pid = int(pid_file.read_text().strip())
            if pid and _process_alive(pid):
                print("Waiting for existing warm PID...")
            else:
                pid = _launch_comfy(pid_file)
        else:
            pid = _launch_comfy(pid_file)
        for attempt in range(1, 121):
            if server_up():
                break
            time.sleep(2)
            if attempt == 120:
                log_tail = _log_file().read_text(encoding="utf-8") if _log_file().is_file() else ""
                raise RuntimeError(
                    f"ComfyUI did not start within 240s\n{log_tail[-4000:]}"
                )
        print(f"ComfyUI ready (pid {pid_file.read_text().strip()})")

    lock_pid_file = _lock_pid_file()
    if lock_pid_file.is_file():
        try:
            lpid = int(lock_pid_file.read_text().strip())
        except ValueError:
            lpid = 0
        if lpid and _process_alive(lpid):
            print("GPU lock already held")
            return
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [
            "bash",
            "-c",
            f'exec 9>>"{LOCK}"; flock 9; while kill -0 $$ 2>/dev/null; do sleep 3600; done',
        ],
        start_new_session=True,
    )
    lock_pid_file.write_text(str(proc.pid), encoding="utf-8")
    print(f"Holding {LOCK} (pid {proc.pid})")


def _launch_comfy(pid_file: Path) -> int:
    print(f"Starting warm ComfyUI on {HOST}:{PORT}...")
    log_path = _log_file()
    with log_path.open("ab") as log_handle:
        proc = subprocess.Popen(
            [
                str(COMFY_ROOT / ".venv/bin/python"),
                "main.py",
                "--listen",
                HOST,
                "--port",
                str(PORT),
                "--disable-auto-launch",
            ],
            cwd=COMFY_ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_server() -> None:
    pid_file = _pid_file()
    if pid_file.is_file():
        pid = int(pid_file.read_text().strip())
        if _process_alive(pid):
            os.kill(pid, 15)
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            print(f"Stopped ComfyUI pid {pid}")
        pid_file.unlink(missing_ok=True)
    _lock_pid_file().unlink(missing_ok=True)
    print("Released GPU lock")
    if server_up():
        print(f"Warning: something still responds on :{PORT}", flush=True)


def status() -> None:
    print(f"server: {'up' if server_up() else 'down'} ({HOST}:{PORT})")
    pid_file = _pid_file()
    print(f"pid_file: {pid_file.read_text().strip() if pid_file.is_file() else 'none'}")
    lock_file = _lock_pid_file()
    print(f"lock_pid: {lock_file.read_text().strip() if lock_file.is_file() else 'none'}")
    if shutil.which("nvidia-smi"):
        subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_gpu_memory",
                "--format=csv",
            ],
            check=False,
        )


def generate(
    *,
    lyrics: Path,
    caption: Path,
    duration: int = 120,
    seed: int = 7,
    out: Path | None = None,
    play: bool = True,
) -> Path:
    if not lyrics.is_file():
        raise FileNotFoundError(f"lyrics file not found: {lyrics}")
    if not caption.is_file():
        raise FileNotFoundError(f"caption file not found: {caption}")
    if not server_up():
        start_server()

    slug = f"music3-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    with tempfile.TemporaryDirectory() as tmp:
        workflow_path = Path(tmp) / "workflow.json"
        workflow.build_workflow(
            float(duration),
            seed,
            caption,
            lyrics,
            f"audio/{slug}",
            workflow_path,
        )
        print(f"Generating {duration}s on warm server (seed {seed})...")
        start = time.time()
        subprocess.run(
            [
                str(COMFY_BIN),
                "--workspace",
                str(COMFY_ROOT),
                "--skip-prompt",
                "run",
                "--workflow",
                str(workflow_path),
                "--wait",
                "--host",
                HOST,
                "--port",
                str(PORT),
                "--timeout",
                "7200",
                "--no-notify",
            ],
            check=True,
        )
        wall = time.time() - start

    flac = _latest_flac(slug)
    if flac is None:
        raise RuntimeError("Generation failed — no output file found")
    if out is None:
        out = _home() / "output" / f"{slug}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(flac), str(out)], check=True, capture_output=True)
    dur = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(out),
        ],
        text=True,
    ).strip()
    print(f"\nDone in {wall:.1f}s (warm)")
    print(f"Duration: {dur}s")
    print(f"Output:   {out}")
    if play:
        _play_wav(out)
    return out


def _latest_flac(slug: str) -> Path | None:
    audio_dir = COMFY_ROOT / "output" / "audio"
    matches = sorted(audio_dir.glob(f"{slug}*.flac"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _play_wav(path: Path) -> None:
    if shutil.which("pw-play"):
        subprocess.run(["pw-play", str(path)], check=False)
    elif shutil.which("aplay"):
        subprocess.run(["aplay", "-q", str(path)], check=False)
