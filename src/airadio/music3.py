"""Talk to a running ComfyUI + MiniMax Music 3 install over HTTP."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from airadio import workflow
from airadio.paths import user_home
from airadio.workflow import EMPTY_LATENT_NODE, TEXT_ENCODE_NODE

HOST = os.environ.get("AIRADIO_COMFY_HOST", "127.0.0.1")
PORT = int(os.environ.get("AIRADIO_COMFY_PORT", "8188"))

COMFYUI_REPO = "https://github.com/comfyanonymous/ComfyUI"
MUSIC3_GUIDE = "https://docs.comfy.org/tutorials/audio/minimax/minimax-music-3"


def base_url() -> str:
    return f"http://{HOST}:{PORT}"


def _get_json(path: str, *, timeout: float = 5.0) -> dict | list:
    url = f"{base_url()}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(path: str, payload: dict, *, timeout: float = 30.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url()}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def server_up() -> bool:
    try:
        _get_json("/system_stats", timeout=3.0)
        return True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False


def music3_nodes_present() -> bool:
    try:
        info = _get_json("/object_info", timeout=10.0)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False
    if not isinstance(info, dict):
        return False
    return TEXT_ENCODE_NODE in info and EMPTY_LATENT_NODE in info


def ready() -> bool:
    """True when ComfyUI is reachable and exposes MiniMax Music 3 nodes."""
    return server_up() and music3_nodes_present()


def unreachable_message() -> str:
    endpoint = base_url()
    return (
        "airadio is your personal radio station using your local install of ComfyUI\n"
        "and MiniMax Music 3!\n"
        "\n"
        f"I can't talk to ComfyUI at {endpoint} yet.\n"
        "\n"
        "Please either:\n"
        "  • Start ComfyUI (with MiniMax Music 3) so it's listening there, or\n"
        "  • Install them if you haven't:\n"
        "\n"
        "      1. ComfyUI\n"
        f"         {COMFYUI_REPO}\n"
        "\n"
        "      2. MiniMax Music 3 (follow this guide — it covers the model files too)\n"
        f"         {MUSIC3_GUIDE}\n"
        "\n"
        "Then rerun: airadio\n"
    )


def require_ready() -> bool:
    """Print guidance and return False if ComfyUI + Music 3 is unreachable."""
    if ready():
        return True
    print(unreachable_message(), end="", flush=True)
    return False


def generate(
    *,
    lyrics: Path,
    caption: Path,
    duration: int = 120,
    seed: int = 7,
    out: Path | None = None,
    play: bool = True,
    verbose: bool = True,
) -> Path:
    if not lyrics.is_file():
        raise FileNotFoundError(f"lyrics file not found: {lyrics}")
    if not caption.is_file():
        raise FileNotFoundError(f"caption file not found: {caption}")
    if not require_ready():
        raise RuntimeError("ComfyUI + MiniMax Music 3 is not reachable")

    slug = f"airadio-{time.strftime('%Y%m%d-%H%M%S')}-{seed}"
    prompt = workflow.build_prompt(
        float(duration),
        seed,
        caption.read_text(encoding="utf-8"),
        lyrics.read_text(encoding="utf-8"),
        f"audio/{slug}",
    )
    if verbose:
        print(f"Generating {duration}s via {base_url()} (seed {seed})...", flush=True)

    started = time.time()
    prompt_id = _queue_prompt(prompt)
    if verbose:
        print(f"Queued prompt {prompt_id}", flush=True)
    outputs = _wait_for_prompt(prompt_id, timeout_s=max(600.0, duration * 60.0))
    audio_meta = _first_audio_output(outputs)
    if audio_meta is None:
        raise RuntimeError("Generation finished but no audio output was returned")

    if out is None:
        out = user_home() / "output" / f"{slug}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)

    raw = out.with_suffix(Path(audio_meta["filename"]).suffix or ".flac")
    _download_view(audio_meta, raw)
    if raw.suffix.lower() == ".wav":
        if raw.resolve() != out.resolve():
            shutil.move(str(raw), str(out))
    else:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(raw), str(out)],
            check=True,
            capture_output=True,
        )
        raw.unlink(missing_ok=True)

    wall = time.time() - started
    if verbose:
        dur = _probe_duration(out)
        print(f"\nDone in {wall:.1f}s", flush=True)
        print(f"Duration: {dur}s", flush=True)
        print(f"Output:   {out}", flush=True)
    if play:
        _play_wav(out)
    return out


def _queue_prompt(prompt: dict) -> str:
    client_id = str(uuid.uuid4())
    result = _post_json("/prompt", {"prompt": prompt, "client_id": client_id})
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not accept prompt: {result}")
    return str(prompt_id)


def _wait_for_prompt(prompt_id: str, *, timeout_s: float) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            history = _get_json(f"/history/{prompt_id}", timeout=10.0)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            time.sleep(2)
            continue
        if isinstance(history, dict) and prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status") or {}
            if status.get("completed") or entry.get("outputs"):
                status_str = status.get("status_str", "success")
                if status_str == "error":
                    raise RuntimeError(f"ComfyUI prompt failed: {status}")
                return entry.get("outputs") or {}
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}")


def _first_audio_output(outputs: dict) -> dict | None:
    for node_out in outputs.values():
        if not isinstance(node_out, dict):
            continue
        for item in node_out.get("audio") or []:
            if isinstance(item, dict) and item.get("filename"):
                return item
    return None


def _download_view(meta: dict, dest: Path) -> None:
    query = urllib.parse.urlencode(
        {
            "filename": meta["filename"],
            "subfolder": meta.get("subfolder") or "",
            "type": meta.get("type") or "output",
        }
    )
    url = f"{base_url()}/view?{query}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        dest.write_bytes(resp.read())


def _probe_duration(path: Path) -> str:
    return subprocess.check_output(
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


def _play_wav(path: Path) -> None:
    if shutil.which("pw-play"):
        subprocess.run(["pw-play", str(path)], check=False)
    elif shutil.which("aplay"):
        subprocess.run(["aplay", "-q", str(path)], check=False)
