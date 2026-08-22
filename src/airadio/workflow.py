"""Build API-format ComfyUI prompts for MiniMax Music 3."""

from __future__ import annotations

import json
from pathlib import Path

# Filenames from the official Comfy-Org MiniMax Music 3 pack (INT8 / low-VRAM set).
DIT_NAME = "minimax_music3_dit_int8_convrot.safetensors"
TEXT_ENCODER_NAME = "minimax_music3_text_encoder_pruned_int8_convrot.safetensors"
VAE_NAME = "minimax_music3_dav.safetensors"

TEXT_ENCODE_NODE = "MiniMaxMusic3TextEncode"
EMPTY_LATENT_NODE = "EmptyMiniMaxMusic3LatentAudio"


def build_prompt(
    duration: float,
    seed: int,
    caption: str,
    lyrics: str,
    output_prefix: str,
) -> dict:
    """Return a ComfyUI API-format prompt graph for MiniMax Music 3."""
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": DIT_NAME,
                "weight_dtype": "default",
            },
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": TEXT_ENCODER_NAME,
                "type": "minimax",
            },
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": VAE_NAME},
        },
        "4": {
            "class_type": TEXT_ENCODE_NODE,
            "inputs": {
                "clip": ["2", 0],
                "caption": caption.strip(),
                "lyrics": lyrics.strip(),
                "seed": int(seed),
                "max_duration": float(duration),
                "cfg_scale": 1.5,
                "top_k": 50,
            },
        },
        "5": {
            "class_type": EMPTY_LATENT_NODE,
            "inputs": {"seconds": float(duration), "batch_size": 1},
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["4", 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
                "seed": int(seed),
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


def build_workflow(
    duration: float,
    seed: int,
    caption_file: Path,
    lyrics_file: Path,
    output_prefix: str,
    out_json: Path,
) -> Path:
    """Write an API-format workflow JSON (compat helper)."""
    prompt = build_prompt(
        duration,
        seed,
        caption_file.read_text(encoding="utf-8"),
        lyrics_file.read_text(encoding="utf-8"),
        output_prefix,
    )
    out_json.write_text(json.dumps(prompt, indent=2) + "\n", encoding="utf-8")
    return out_json
