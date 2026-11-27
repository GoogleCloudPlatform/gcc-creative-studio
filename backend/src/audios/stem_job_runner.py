# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Standalone CLI and Cloud Run Job entrypoint for audio stem separation.

Invoked in production by the ``cs-<env>-stems-job`` Cloud Run Job (and locally
as an isolated OS subprocess via ``python -m src.audios.stem_job_runner``) so
memory-intensive HT-Demucs ONNX inference never runs inside web workers.
"""

import argparse
from collections.abc import Sequence
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any

from src.audios.audio_stems import (
    GCS_MODEL_BLOB_PATH,
    STEM_CACHE_SCHEMA_VERSION,
    UI_STEM_ORDER,
    compute_stem_cache_key,
    separate_and_encode_stems_mp3,
)
from src.audios.audio_waveform import extract_audio_waveform_and_duration
from src.common.base_dto import MimeTypeEnum
from src.common.storage_service import GcsService
from src.config.config_service import config_service

logger = logging.getLogger(__name__)


def manifest_blob_path(cache_key: str) -> str:
    """Returns the GCS object path for a cached stem ``manifest.json``."""
    return f"audio_stems_cache/{cache_key}/manifest.json"


def job_record_blob_path(cache_key: str) -> str:
    """Returns the GCS object path for a stem job lifecycle ``job.json``."""
    return f"audio_stems_cache/{cache_key}/job.json"


def read_cached_manifest_sync(
    gcs_service: GcsService,
    cache_key: str,
) -> dict[str, Any] | None:
    """Reads ``manifest.json`` from GCS without logging false NotFound errors."""
    blob_name = manifest_blob_path(cache_key)
    try:
        blob = gcs_service.bucket.blob(blob_name)
        if not blob.exists():
            return None
        payload = json.loads(blob.download_as_bytes().decode("utf-8"))
    except Exception as exc:
        logger.warning(
            "Ignoring unreadable stem cache manifest %s: %s",
            blob_name,
            exc,
        )
        return None

    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != STEM_CACHE_SCHEMA_VERSION
    ):
        return None

    stems_map = payload.get("stems")
    if not isinstance(stems_map, dict):
        return None
    for stem_name in UI_STEM_ORDER:
        entry = stems_map.get(stem_name)
        if not isinstance(entry, dict) or not entry.get("gcs_uri"):
            return None
    return payload


def read_job_record_sync(
    gcs_service: GcsService,
    cache_key: str,
) -> dict[str, Any] | None:
    """Reads ``job.json`` state for ``cache_key`` if present in GCS."""
    blob_name = job_record_blob_path(cache_key)
    try:
        blob = gcs_service.bucket.blob(blob_name)
        if not blob.exists():
            return None
        payload = json.loads(blob.download_as_bytes().decode("utf-8"))
    except Exception as exc:
        logger.warning(
            "Ignoring unreadable stem job record %s: %s",
            blob_name,
            exc,
        )
        return None
    return payload if isinstance(payload, dict) else None


def write_job_record_sync(
    gcs_service: GcsService,
    cache_key: str,
    *,
    status: str,
    source_gcs_uri: str,
    execution_ref: str = "",
    started_at: float | None = None,
    error: str | None = None,
    error_code: int | None = None,
) -> dict[str, Any]:
    """Writes ``job.json`` tracking stem job progress or terminal errors."""
    now = time.time()
    record: dict[str, Any] = {
        "schema_version": STEM_CACHE_SCHEMA_VERSION,
        "status": status,
        "source_gcs_uri": source_gcs_uri,
        "execution_ref": execution_ref,
        "started_at": started_at if started_at is not None else now,
        "updated_at": now,
        "error": error,
        "error_code": error_code,
    }
    gcs_service.upload_bytes_to_gcs(
        json.dumps(record).encode("utf-8"),
        job_record_blob_path(cache_key),
        "application/json",
    )
    return record


def download_model_from_gcs_sync(
    gcs_service: GcsService,
    destination_path: Path,
) -> bool:
    """Downloads cached ONNX weights from GCS when not baked into the image."""
    blob = gcs_service.bucket.blob(GCS_MODEL_BLOB_PATH)
    if not blob.exists():
        return False
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(destination_path))
    return True


def upload_model_to_gcs_sync(
    gcs_service: GcsService,
    source_path: Path,
) -> None:
    """Best-effort mirror of ONNX weights into the project's GCS bucket."""
    gcs_service.upload_file_to_gcs(
        str(source_path),
        GCS_MODEL_BLOB_PATH,
        "application/octet-stream",
    )


def execute_stem_separation_to_gcs_sync(
    gcs_service: GcsService,
    source_gcs_uri: str,
    cache_key: str,
) -> dict[str, Any]:
    """Downloads source audio, streams ONNX separation to MP3s, and writes GCS manifest."""
    cached = read_cached_manifest_sync(gcs_service, cache_key)
    if cached is not None:
        return cached

    audio_bytes = gcs_service.download_bytes_from_gcs(source_gcs_uri)
    if not audio_bytes:
        raise RuntimeError(
            "Failed to download source audio from Cloud Storage."
        )

    encoded_stems = separate_and_encode_stems_mp3(
        audio_bytes,
        cache_dir=config_service.AUDIO_STEM_MODEL_CACHE_DIR,
        model_url=config_service.AUDIO_STEM_MODEL_URL,
        intra_op_threads=config_service.AUDIO_STEM_ORT_THREADS,
        bitrate="192k",
        gcs_download_fn=lambda dest: download_model_from_gcs_sync(
            gcs_service, dest
        ),
        gcs_upload_fn=lambda src: upload_model_to_gcs_sync(gcs_service, src),
    )

    stems_manifest: dict[str, dict[str, Any]] = {}
    overall_duration: float | None = None

    for stem_name in UI_STEM_ORDER:
        encoded = encoded_stems[stem_name]
        waveform, duration_sec = extract_audio_waveform_and_duration(
            encoded.mp3_bytes,
            MimeTypeEnum.AUDIO_MPEG.value,
        )
        effective_duration = (
            duration_sec
            if duration_sec is not None
            else encoded.duration_seconds
        )
        if overall_duration is None and effective_duration is not None:
            overall_duration = effective_duration

        stem_blob_name = f"audio_stems_cache/{cache_key}/{stem_name}.mp3"
        stem_gcs_uri = gcs_service.upload_bytes_to_gcs(
            encoded.mp3_bytes,
            stem_blob_name,
            MimeTypeEnum.AUDIO_MPEG.value,
        )
        if not stem_gcs_uri:
            raise RuntimeError(
                "Failed to store separated audio stems in Cloud Storage."
            )

        stems_manifest[stem_name] = {
            "gcs_uri": stem_gcs_uri,
            "waveform": waveform,
            "duration_seconds": effective_duration,
            "peak_level": encoded.peak_level,
            "has_energy": encoded.has_energy,
        }

    manifest: dict[str, Any] = {
        "schema_version": STEM_CACHE_SCHEMA_VERSION,
        "source_gcs_uri": source_gcs_uri,
        "duration_seconds": overall_duration,
        "stems": stems_manifest,
    }
    manifest_uri = gcs_service.upload_bytes_to_gcs(
        json.dumps(manifest).encode("utf-8"),
        manifest_blob_path(cache_key),
        "application/json",
    )
    if not manifest_uri:
        raise RuntimeError("Failed to write stem manifest to Cloud Storage.")
    return manifest


def run_job_from_args(
    source_gcs_uri: str,
    cache_key: str = "",
    gcs_service: GcsService | None = None,
) -> int:
    """Executes stem separation for ``source_gcs_uri`` and records terminal state."""
    clean_uri = (source_gcs_uri or "").strip()
    if not clean_uri:
        logger.error("STEM_SOURCE_GCS_URI is required.")
        return 2

    resolved_key = (cache_key or "").strip() or compute_stem_cache_key(
        clean_uri
    )
    gcs = gcs_service if gcs_service is not None else GcsService()
    existing_job = read_job_record_sync(gcs, resolved_key) or {}
    started_at = existing_job.get("started_at")
    execution_ref = str(existing_job.get("execution_ref") or "")

    try:
        execute_stem_separation_to_gcs_sync(
            gcs_service=gcs,
            source_gcs_uri=clean_uri,
            cache_key=resolved_key,
        )
        write_job_record_sync(
            gcs,
            resolved_key,
            status="completed",
            source_gcs_uri=clean_uri,
            execution_ref=execution_ref,
            started_at=(
                started_at if isinstance(started_at, (int, float)) else None
            ),
        )
        logger.info(
            "Completed audio stem job for %s (cache_key=%s).",
            clean_uri,
            resolved_key,
        )
        return 0
    except ValueError as exc:
        logger.warning(
            "Audio stem validation error for %s: %s",
            clean_uri,
            exc,
        )
        try:
            write_job_record_sync(
                gcs,
                resolved_key,
                status="failed",
                source_gcs_uri=clean_uri,
                execution_ref=execution_ref,
                started_at=(
                    started_at if isinstance(started_at, (int, float)) else None
                ),
                error=str(exc),
                error_code=422,
            )
        except Exception as write_err:
            logger.error(
                "Failed to record validation error to GCS: %s", write_err
            )
        return 1
    except Exception as exc:
        logger.error(
            "Audio stem job failed for %s: %s",
            clean_uri,
            exc,
            exc_info=True,
        )
        try:
            write_job_record_sync(
                gcs,
                resolved_key,
                status="failed",
                source_gcs_uri=clean_uri,
                execution_ref=execution_ref,
                started_at=(
                    started_at if isinstance(started_at, (int, float)) else None
                ),
                error=str(exc) or "Audio stem separation failed.",
                error_code=502,
            )
        except Exception as write_err:
            logger.error("Failed to record job failure to GCS: %s", write_err)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for Cloud Run Job and local subprocess invocations."""
    parser = argparse.ArgumentParser(
        description="Run HT-Demucs 6-stem separation into GCS cache.",
    )
    parser.add_argument(
        "--source-gcs-uri",
        default=os.getenv("STEM_SOURCE_GCS_URI", ""),
        help="gs:// URI of the source audio file.",
    )
    parser.add_argument(
        "--cache-key",
        default=os.getenv("STEM_CACHE_KEY", ""),
        help="Deterministic stem cache key (auto-computed if omitted).",
    )
    parsed = parser.parse_args(list(argv) if argv is not None else None)
    return run_job_from_args(
        source_gcs_uri=parsed.source_gcs_uri,
        cache_key=parsed.cache_key,
    )


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(main())
