# airadio — local AI radio with MiniMax Music 3

**airadio** is your personal radio station using your local install of
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) and
[MiniMax Music 3](https://docs.comfy.org/tutorials/audio/minimax/minimax-music-3).

It generates ~2-minute songs over ComfyUI’s normal HTTP API, plays them with
tail fades, and fills gaps with interstitials or library tracks until the next
song is ready.

```bash
pip install airadio
# start ComfyUI yourself (with MiniMax Music 3), then:
airadio
```

Each new song gets a random two-word title that primes generation and becomes
the filename (`velvet-garden4289.wav`).

## What you need

1. **ComfyUI** running locally (default `http://127.0.0.1:8188`)
2. **MiniMax Music 3** installed *into* that ComfyUI (nodes + model files)
3. Linux playback (`pw-play` or `aplay`), `ffmpeg` / `ffprobe`, Python 3.10+

airadio does **not** start ComfyUI for you and does **not** need comfy-cli or
any side “Music 3” client. If it can’t talk to ComfyUI, it tells you to start
or install it, then exit.

## Install airadio

```bash
pip install airadio
# or from source:
git clone https://github.com/Decentricity/interdimensional-radio.git
cd interdimensional-radio
pip install -e .
```

## Install ComfyUI + MiniMax Music 3

Follow the official guides (Music 3 lives *inside* ComfyUI):

1. ComfyUI — https://github.com/comfyanonymous/ComfyUI  
2. MiniMax Music 3 — https://docs.comfy.org/tutorials/audio/minimax/minimax-music-3  

That guide covers the model files. Use the low-VRAM INT8 set if you have ~12 GB
VRAM (same set this project was tested with).

Start ComfyUI the normal way so it listens on port **8188**, then run:

```bash
airadio
```

Optional: keep radio data (library, interstitials, staging) in a custom folder:

```bash
export AIRADIO_HOME="$PWD"   # auto-detected if ./library exists
airadio
```

## CLI

| Command | Purpose |
|---------|---------|
| `airadio` | Start the radio loop |
| `airadio run` | Same as above |
| `airadio title` | Print random two-word song titles |

## How it works

```
┌─────────┐     HTTP :8188      ┌─────────────────────────────┐
│ airadio │ ──────────────────▶ │ Your ComfyUI + Music 3      │
└────┬────┘                     └─────────────────────────────┘
     │
     ├── library/         saved songs
     ├── interstitials/   gap-fill clips
     └── .radio-staging/  in-flight generation
```

1. **Check** — can airadio reach ComfyUI with Music 3 nodes? If not, print install/start help and exit.
2. **Pipeline** — while a song plays, the next one generates in the background.
3. **Fill** — if gen is not ready: interstitials, then a library track; repeat.
4. **Archive** — finished songs land in `library/` with catalog metadata.

## Hardware

Tested on **NVIDIA GeForce RTX 4070 Ti (12 GB VRAM)** with the **INT8** MiniMax
Music 3 weights (~11 GB on disk; ~10–11 GB VRAM for a 120s generation).

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `AIRADIO_HOME` | `~/.local/share/airadio` (or cwd if `library/` exists) | Radio data root |
| `IDR_ROOT` | *(alias for `AIRADIO_HOME`)* | Legacy name |
| `AIRADIO_COMFY_HOST` | `127.0.0.1` | ComfyUI host |
| `AIRADIO_COMFY_PORT` | `8188` | ComfyUI port |
| `AIRADIO_PROMPTS` | bundled package prompts | Override prompt directory |

## Prompts and titles

Bundled under the package:

- Caption / lyrics templates for generation
- Title word lists for two-word song names
- Interstitial scripts and prompts

## License

Application code: MIT (see [LICENSE](LICENSE)).

MiniMax Music 3 weights are distributed separately under their own terms by
MiniMax / Comfy-Org.
