"""Append-only provenance for generated interstitial audio."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from airadio import __version__
from airadio.storage import atomic_write_json, atomic_write_text

SCHEMA_VERSION = 1
CATALOG_VERSION = 1


@dataclass(frozen=True)
class AuditIssue:
    audio: Path
    problem: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lyrics_sidecar_path(audio: Path) -> Path:
    return audio.with_suffix(".lyrics.txt")


def provenance_sidecar_path(audio: Path) -> Path:
    return audio.with_suffix(".provenance.json")


def canonical_home(home: Path) -> Path:
    """Follow a relocated interstitial/audio directory back to its data root."""
    logical = home.expanduser().resolve()
    audio_root = logical / "interstitials" / "audio"
    if audio_root.exists():
        resolved_audio = audio_root.resolve()
        if resolved_audio.name == "audio" and resolved_audio.parent.name == "interstitials":
            return resolved_audio.parents[1]
    return logical


def provenance_root(home: Path) -> Path:
    return canonical_home(home) / "interstitials" / "provenance"


def catalog_path(home: Path) -> Path:
    return provenance_root(home) / "catalog.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_ref(path: Path, home: Path) -> dict[str, str]:
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(home.resolve())
    except ValueError:
        return {"scope": "absolute", "path": str(resolved)}
    return {"scope": "airadio_home", "path": relative.as_posix()}


def _relative_to_home(path: Path, home: Path) -> str:
    try:
        return path.resolve().relative_to(home.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"path is outside AIRADIO_HOME: {path}") from exc


def _load_catalog(home: Path) -> dict[str, Any]:
    path = catalog_path(home)
    if not path.is_file():
        return {"version": CATALOG_VERSION, "updated_at": None, "clips": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != CATALOG_VERSION or not isinstance(data.get("clips"), dict):
        raise ValueError(f"unsupported interstitial provenance catalog: {path}")
    return data


def _archive_file(source: Path, destination: Path) -> None:
    """Archive independent bytes so later in-place edits cannot alter history."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _new_generation_id(audio_hash: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{stamp}-{audio_hash[:12]}-{uuid.uuid4().hex[:8]}"


def record_generation(
    home: Path,
    audio: Path,
    *,
    lyrics: str,
    kind: str,
    style: str,
    backend: str,
    source_script: Path | None = None,
    caption: Path | None = None,
    seed: int | None = None,
    duration_s: float | int | None = None,
    gender: str | None = None,
    status: str = "generated",
    generated_at: str | None = None,
    evidence: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record one successful output and archive its exact audio and inputs."""
    root = canonical_home(home)
    wav = audio.expanduser().resolve()
    audio_rel = _relative_to_home(wav, root)
    expected_audio_root = (root / "interstitials" / "audio").resolve()
    try:
        wav.relative_to(expected_audio_root)
    except ValueError as exc:
        raise ValueError(f"interstitial audio is outside {expected_audio_root}: {wav}") from exc
    if not wav.is_file():
        raise FileNotFoundError(wav)
    if not lyrics.strip():
        raise ValueError("interstitial lyrics cannot be empty")

    audio_hash = sha256_file(wav)
    lyric_bytes = lyrics.encode("utf-8")
    lyrics_hash = sha256_bytes(lyric_bytes)
    generation_id = _new_generation_id(audio_hash)
    history_dir = provenance_root(root) / "history" / generation_id
    history_audio = history_dir / "audio.wav"
    history_lyrics = history_dir / "lyrics.txt"
    history_record = history_dir / "provenance.json"

    catalog = _load_catalog(root)
    prior = catalog["clips"].get(audio_rel)
    prior_id = prior.get("current_generation_id") if isinstance(prior, dict) else None

    _archive_file(wav, history_audio)
    atomic_write_text(history_lyrics, lyrics)

    source_data: dict[str, Any] | None = None
    if source_script is not None and source_script.is_file():
        source_text = source_script.read_text(encoding="utf-8")
        archived = history_dir / "source-script.txt"
        atomic_write_text(archived, source_text)
        source_data = {
            "original": _path_ref(source_script, root),
            "archived_path": _relative_to_home(archived, root),
            "sha256": sha256_bytes(source_text.encode("utf-8")),
        }

    caption_data: dict[str, Any] | None = None
    if caption is not None and caption.is_file():
        caption_text = caption.read_text(encoding="utf-8")
        archived = history_dir / "caption.txt"
        atomic_write_text(archived, caption_text)
        caption_data = {
            "original": _path_ref(caption, root),
            "archived_path": _relative_to_home(archived, root),
            "sha256": sha256_bytes(caption_text.encode("utf-8")),
        }

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generation_id": generation_id,
        "status": status,
        "generated_at": generated_at or _utc_now(),
        "recorded_at": _utc_now(),
        "airadio_version": __version__,
        "kind": kind,
        "style": style,
        "backend": backend,
        "audio": {
            "current_path": audio_rel,
            "history_path": _relative_to_home(history_audio, root),
            "sha256": audio_hash,
            "bytes": wav.stat().st_size,
        },
        "lyrics": {
            "current_path": _relative_to_home(lyrics_sidecar_path(wav), root),
            "history_path": _relative_to_home(history_lyrics, root),
            "sha256": lyrics_hash,
        },
        "parameters": {"seed": seed, "duration_s": duration_s},
        "supersedes": prior_id,
    }
    if source_data:
        record["source_script"] = source_data
    if caption_data:
        record["caption"] = caption_data
    if gender:
        record["gender"] = gender
    if evidence:
        record["evidence"] = evidence
    if extra:
        record["extra"] = extra

    atomic_write_json(history_record, record)
    atomic_write_text(lyrics_sidecar_path(wav), lyrics)
    atomic_write_json(provenance_sidecar_path(wav), record)

    history_ids: list[str] = []
    if isinstance(prior, dict):
        history_ids = [str(item) for item in prior.get("generation_ids", [])]
    if generation_id not in history_ids:
        history_ids.append(generation_id)
    catalog["clips"][audio_rel] = {
        "current_generation_id": generation_id,
        "generation_ids": history_ids,
        "provenance_path": _relative_to_home(provenance_sidecar_path(wav), root),
        "lyrics_path": _relative_to_home(lyrics_sidecar_path(wav), root),
    }
    catalog["updated_at"] = _utc_now()
    atomic_write_json(catalog_path(root), catalog)
    return record


def resolve_audio(home: Path, value: Path) -> Path:
    home = canonical_home(home)
    candidates = [value]
    if not value.is_absolute():
        candidates.extend([home / value, home / "interstitials" / "audio" / value])
    for candidate in candidates:
        if candidate.is_file():
            return candidate.expanduser().resolve()
    raise FileNotFoundError(value)


def load_record(audio: Path) -> dict[str, Any]:
    sidecar = provenance_sidecar_path(audio)
    if not sidecar.is_file():
        raise FileNotFoundError(f"no provenance sidecar for {audio}")
    return json.loads(sidecar.read_text(encoding="utf-8"))


def read_lyrics(audio: Path) -> str:
    record = load_record(audio)
    sidecar = lyrics_sidecar_path(audio)
    if not sidecar.is_file():
        raise FileNotFoundError(f"no lyrics sidecar for {audio}")
    text = sidecar.read_text(encoding="utf-8")
    if sha256_bytes(text.encode("utf-8")) != record.get("lyrics", {}).get("sha256"):
        raise ValueError(f"lyrics hash does not match provenance for {audio}")
    return text


def audit(home: Path) -> list[AuditIssue]:
    root = canonical_home(home)
    audio_root = root / "interstitials" / "audio"
    issues: list[AuditIssue] = []
    if not audio_root.is_dir():
        return issues
    try:
        catalog = _load_catalog(root)
    except (ValueError, json.JSONDecodeError) as exc:
        return [AuditIssue(catalog_path(root), str(exc))]
    referenced_history: set[str] = set()
    for wav in sorted(audio_root.rglob("*.wav")):
        try:
            record = load_record(wav)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            issues.append(AuditIssue(wav, str(exc)))
            continue
        if record.get("schema_version") != SCHEMA_VERSION:
            issues.append(AuditIssue(wav, "unsupported provenance schema"))
            continue
        if sha256_file(wav) != record.get("audio", {}).get("sha256"):
            issues.append(AuditIssue(wav, "audio hash mismatch"))
        try:
            read_lyrics(wav)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            issues.append(AuditIssue(wav, str(exc)))
        audio_rel = _relative_to_home(wav, root)
        catalog_entry = catalog["clips"].get(audio_rel)
        if not isinstance(catalog_entry, dict):
            issues.append(AuditIssue(wav, "catalog entry missing"))
        elif catalog_entry.get("current_generation_id") != record.get("generation_id"):
            issues.append(AuditIssue(wav, "catalog current generation does not match sidecar"))

    for audio_rel, entry in catalog["clips"].items():
        audio = root / audio_rel
        if not audio.is_file():
            issues.append(AuditIssue(audio, "catalog points to missing audio"))
        generation_ids = entry.get("generation_ids", []) if isinstance(entry, dict) else []
        if not generation_ids:
            issues.append(AuditIssue(audio, "catalog has no generation history"))
            continue
        for generation_id in generation_ids:
            generation_id = str(generation_id)
            referenced_history.add(generation_id)
            history_dir = provenance_root(root) / "history" / generation_id
            history_record = history_dir / "provenance.json"
            try:
                record = json.loads(history_record.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError) as exc:
                issues.append(AuditIssue(audio, f"invalid history record {generation_id}: {exc}"))
                continue
            if record.get("generation_id") != generation_id:
                issues.append(AuditIssue(audio, f"history ID mismatch for {generation_id}"))
            for section, field, label in (
                ("audio", "history_path", "history audio"),
                ("lyrics", "history_path", "history lyrics"),
            ):
                value = record.get(section, {}).get(field)
                archived = root / str(value) if value else None
                if archived is None or not archived.is_file():
                    issues.append(AuditIssue(audio, f"{label} missing for {generation_id}"))
                elif sha256_file(archived) != record.get(section, {}).get("sha256"):
                    issues.append(AuditIssue(audio, f"{label} hash mismatch for {generation_id}"))
            for section, label in (("source_script", "source script"), ("caption", "caption")):
                data = record.get(section)
                if not isinstance(data, dict):
                    continue
                archived = root / str(data.get("archived_path"))
                if not archived.is_file():
                    issues.append(AuditIssue(audio, f"archived {label} missing for {generation_id}"))
                elif sha256_file(archived) != data.get("sha256"):
                    issues.append(AuditIssue(audio, f"archived {label} hash mismatch for {generation_id}"))

    history_root = provenance_root(root) / "history"
    if history_root.is_dir():
        for directory in history_root.iterdir():
            if directory.is_dir() and directory.name not in referenced_history:
                issues.append(AuditIssue(directory, "orphaned history generation"))
    return issues
