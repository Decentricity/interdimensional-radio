# Interdimensional Radio

A local AI radio loop: generate ~2-minute songs with [MiniMax Music 3](https://docs.comfy.org/tutorials/audio/minimax/minimax-music-3) in the background, play them with tail fades, and fill gaps with prerecorded interstitials or library tracks until the next song is ready.

Each new song gets a random two-word title that primes generation and becomes the filename (`velvet-garden4289.wav`).

## Hardware

Tested on **NVIDIA GeForce RTX 4070 Ti (12 GB VRAM)**. This repo uses the **INT8-quantized** MiniMax Music 3 weights (~11 GB on disk; ~10–11 GB VRAM during a 120s generation).

| Profile | GPU VRAM | Model set |
|--------|----------|-----------|
| **Recommended (this repo)** | 12 GB+ | INT8 DiT + pruned INT8 text encoder + DAV VAE |
| Higher quality | 16 GB+ | FP16 DiT + pruned BF16/FP16 text encoder + DAV VAE |
| Minimum | 8 GB (tight) | INT8 DiT + pruned INT8 text encoder; shorten `--duration` |

You also need:

- **Linux** (tested; PipeWire `pw-play` or ALSA `aplay` for playback)
- **~15 GB free disk** for the three model files
- **ffmpeg** and **ffprobe** on `PATH`
- **Python 3.10+**
- **curl**, **flock** (util-linux)

## Quick start

```bash
git clone https://github.com/Decentricity/interdimensional-radio.git
cd interdimensional-radio
export IDR_ROOT="$PWD"   # optional; auto-detected from script location

# 1. Install MiniMax Music 3 + ComfyUI (see below)
# 2. Add scripts to PATH (or symlink)
mkdir -p ~/.local/bin
ln -sf "$PWD/bin/music3-warm" ~/.local/bin/
ln -sf "$PWD/bin/interdimensional-radio" ~/.local/bin/

# 3. Generate interstitial clips (optional but recommended)
python3 bin/generate-interstitials.py music3-both

# 4. Run the radio
interdimensional-radio
```

Set `IDR_ROOT` if you keep the repo outside the default layout. Runtime state (staging, logs, pid files) lives under `$IDR_ROOT/.radio-staging/`.

## Install MiniMax Music 3

Interdimensional Radio drives generation through **ComfyUI** with native MiniMax Music 3 nodes. Official docs: [ComfyUI MiniMax Music 3 tutorial](https://docs.comfy.org/tutorials/audio/minimax/minimax-music-3).

### 1. ComfyUI (0.33.0+)

ComfyUI must include the MiniMax Music 3 audio nodes. Update to the latest release or nightly if the template is missing.

```bash
git clone https://github.com/comfyanonymous/ComfyUI.git ~/.local/share/comfy-music3
cd ~/.local/share/comfy-music3
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Or use the [ComfyUI installer](https://www.comfy.org/download) and point `COMFY_ROOT` at that install.

### 2. Download model weights

Download from the [Comfy-Org MiniMax Music 3 Hugging Face repo](https://huggingface.co/Comfy-Org/minimax-music-3_ComfyUI) (Apache 2.0).

**Low-VRAM set (used by this repo):**

| File | Install path under `$COMFY_ROOT` |
|------|----------------------------------|
| `minimax_music3_dit_int8_convrot.safetensors` (~2.5 GB) | `models/diffusion_models/` |
| `minimax_music3_text_encoder_pruned_int8_convrot.safetensors` (~8.6 GB) | `models/text_encoders/` |
| `minimax_music3_dav.safetensors` (~207 MB) | `models/vae/` |

Example with `huggingface-cli`:

```bash
export COMFY_ROOT="${COMFY_ROOT:-$HOME/.local/share/comfy-music3}"
pip install huggingface_hub
huggingface-cli download Comfy-Org/minimax-music-3_ComfyUI \
  minimax_music3_dit_int8_convrot.safetensors \
  --local-dir "$COMFY_ROOT/models/diffusion_models"
huggingface-cli download Comfy-Org/minimax-music-3_ComfyUI \
  minimax_music3_text_encoder_pruned_int8_convrot.safetensors \
  --local-dir "$COMFY_ROOT/models/text_encoders"
huggingface-cli download Comfy-Org/minimax-music-3_ComfyUI \
  minimax_music3_dav.safetensors \
  --local-dir "$COMFY_ROOT/models/vae"
```

Restart ComfyUI after placing files. If a loader dropdown is empty, the file is in the wrong folder or still downloading.

### 3. comfy-cli (generation client)

```bash
export MINIMAX_ROOT="${MINIMAX_ROOT:-$HOME/.local/share/minimax-music3}"
mkdir -p "$MINIMAX_ROOT"
python3 -m venv "$MINIMAX_ROOT/venv"
"$MINIMAX_ROOT/venv/bin/pip" install comfy-cli
```

`music3-warm` expects the CLI at `$MINIMAX_ROOT/venv/bin/comfy`. Override with `COMFY_BIN` if needed.

### 4. Smoke test

```bash
export IDR_ROOT=/path/to/interdimensional-radio
music3-warm start
music3-warm gen \
  --lyrics prompts/normie-control.lyrics.template.txt \
  --prompt prompts/normie-control.caption.txt \
  --duration 30 --seed 1 --out /tmp/test.wav --no-play
music3-warm stop
```

For a real generation, build lyrics from a title first (`python3 prompts/song_title.py`); the radio does this automatically.

## How it works

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│ interdimensional│────▶│ music3-warm      │────▶│ ComfyUI     │
│ -radio          │     │ (warm server)    │     │ MiniMax M3  │
└────────┬────────┘     └──────────────────┘     └─────────────┘
         │
         ├── library/          saved songs (title+seed.wav)
         ├── interstitials/    gap-fill clips
         └── prompts/          caption, lyrics template, title words
```

1. **Startup** — pick a random library track as warm-up; start generating the first titled song.
2. **Pipeline** — while a song plays, the next one generates (~2–3 min for 120s INT8).
3. **Fill** — if gen is not ready: up to 40s of interstitials, then a full library track; repeat.
4. **Archive** — each finished song is copied to `library/` as `{phrase}{seed}.wav` with catalog metadata.

## Scripts

| Script | Purpose |
|--------|---------|
| `bin/interdimensional-radio` | Main radio loop |
| `bin/music3-warm` | Keep ComfyUI warm; `start` / `stop` / `status` / `gen` |
| `bin/generate-interstitials.py` | Batch-generate station IDs, ads, DJ chatter |
| `workflows/build_api_workflow.py` | Build ComfyUI API workflow JSON for a gen job |
| `prompts/song_title.py` | Random two-word title generator |

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `IDR_ROOT` | repo root | Project root (prompts, library, staging) |
| `COMFY_ROOT` | `~/.local/share/comfy-music3` | ComfyUI install |
| `MINIMAX_ROOT` | `~/.local/share/minimax-music3` | comfy-cli venv |
| `IDR_WORKFLOWS` | `$IDR_ROOT/workflows` | Workflow builder scripts |
| `COMFY_BIN` | `$MINIMAX_ROOT/venv/bin/comfy` | comfy-cli binary |

## Prompts and titles

- **`prompts/normie-control.caption.txt`** — production metadata (genre-neutral pop).
- **`prompts/normie-control.lyrics.template.txt`** — lyrics scaffold; `{title}`, `{word1}`, `{word2}` filled per song.
- **`prompts/song-title-words.json`** — 32×32 word lists for grammatical two-word titles.

Edit the word lists or caption to steer the station sound. The radio writes per-generation caption/lyrics files under `.radio-staging/prompts/`.

## Interstitials

See [interstitials/README.md](interstitials/README.md). Generated WAVs are gitignored; scripts and prompts are included. Regenerate with:

```bash
python3 bin/generate-interstitials.py music3-both
```

## License

Application code in this repository: MIT (see [LICENSE](LICENSE)).

MiniMax Music 3 model weights are distributed separately under Apache 2.0 by MiniMax / Comfy-Org. Download and use of the weights is subject to their license terms.
