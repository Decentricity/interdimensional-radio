"""Build a flat API-format ComfyUI workflow for MiniMax Music 3."""

from __future__ import annotations

import json
from pathlib import Path


def build_workflow(
    duration: float,
    seed: int,
    caption_file: Path,
    lyrics_file: Path,
    output_prefix: str,
    out_json: Path,
) -> Path:
    caption = caption_file.read_text(encoding="utf-8").strip()
    lyrics = lyrics_file.read_text(encoding="utf-8").strip()
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
    out_json.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")
    return out_json
