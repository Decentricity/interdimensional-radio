#!/usr/bin/env python3
"""Build a flat API-format ComfyUI workflow for MiniMax Music 3."""
from __future__ import annotations

import json
import sys
from pathlib import Path

duration = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
seed = int(sys.argv[2]) if len(sys.argv) > 2 else 7
caption_file = sys.argv[3] if len(sys.argv) > 3 else str(
    Path.home() / ".local/share/minimax-music3/prompts/hedgehog-pig.caption.txt"
)
lyrics_file = sys.argv[4] if len(sys.argv) > 4 else str(
    Path.home() / ".local/share/minimax-music3/prompts/hedgehog-pig.lyrics.txt"
)
output_prefix = sys.argv[5] if len(sys.argv) > 5 else f"audio/music3-{int(duration)}s"
out_json = sys.argv[6] if len(sys.argv) > 6 else str(
    Path.home() / f".local/share/comfy-music3-workflows/api-{int(duration)}s.json"
)

caption = Path(caption_file).read_text().strip()
lyrics = Path(lyrics_file).read_text().strip()

workflow = {
    "1": {
        "class_type": "UNETLoader",
        "inputs": {
            "unet_name": "minimax_music3_dit_int8_convrot.safetensors",
            "weight_dtype": "default",
        },
    },
    "2": {
        "class_type": "CLIPLoader",
        "inputs": {
            "clip_name": "minimax_music3_text_encoder_pruned_int8_convrot.safetensors",
            "type": "minimax",
        },
    },
    "3": {
        "class_type": "VAELoader",
        "inputs": {"vae_name": "minimax_music3_dav.safetensors"},
    },
    "4": {
        "class_type": "MiniMaxMusic3TextEncode",
        "inputs": {
            "clip": ["2", 0],
            "caption": caption,
            "lyrics": lyrics,
            "seed": seed,
            "max_duration": duration,
            "cfg_scale": 1.5,
            "top_k": 50,
        },
    },
    "5": {
        "class_type": "EmptyMiniMaxMusic3LatentAudio",
        "inputs": {"seconds": duration, "batch_size": 1},
    },
    "6": {
        "class_type": "KSampler",
        "inputs": {
            "model": ["1", 0],
            "positive": ["4", 0],
            "negative": ["4", 0],
            "latent_image": ["5", 0],
            "seed": seed,
            "steps": 30,
            "cfg": 1.7,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
        },
    },
    "7": {
        "class_type": "VAEDecodeAudioTiled",
        "inputs": {
            "samples": ["6", 0],
            "vae": ["3", 0],
            "tile_size": 1536,
            "overlap": 64,
        },
    },
    "8": {
        "class_type": "SaveAudioAdvanced",
        "inputs": {
            "audio": ["7", 0],
            "filename_prefix": output_prefix,
            "format": "flac",
        },
    },
}

Path(out_json).write_text(json.dumps(workflow, indent=2) + "\n")
print(f"Wrote {out_json} (duration={duration}s, seed={seed})")
