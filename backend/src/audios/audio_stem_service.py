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
"""Service orchestrating audio stem extraction, GCS caching, and gallery persistence."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
import inspect
import logging
from pathlib import Path
import time
from typing import Any
import uuid

from fastapi import Depends, HTTPException
import numpy as np

from src.audios.audio_stems import (
    STEM_LABELS,
    UI_STEM_ORDER,
    compute_stem_cache_key,
    decode_audio_to_stereo_f32,
    encode_stereo_f32_to_mp3,
)
from src.audios.audio_waveform import extract_audio_waveform_and_duration
from src.audios.dto.stem_audio_dto import (
    ExtractStemsDto,
    ExtractStemsResponseDto,
    SaveStemMixDto,
    StemJobStatusEnum,
    StemNameEnum,
    StemPreviewItemDto,
    StemSaveModeEnum,
)
from src.audios.lyria3_text import normalize_audio_analysis
from src.audios.stem_job_launcher import (
    StemJobLauncher,
    get_default_stem_job_launcher,
)
from src.audios.stem_job_runner import (
    read_cached_manifest_sync,
    read_job_record_sync,
    write_job_record_sync,
)
from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.common.base_dto import (
    AspectRatioEnum,
    AssetReferenceDto,
    GenerationModelEnum,
    MimeTypeEnum,
)
from src.common.schema.media_item_model import (
    AssetRoleEnum,
    JobStatusEnum,
    MediaItemModel,
    SourceAssetLink,
    SourceMediaItemLink,
)
from src.common.storage_service import GcsService
from src.folders.output_folder import resolve_output_folder_id
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.images.repository.media_item_repository import MediaRepository
from src.source_assets.repository.source_asset_repository import (
    SourceAssetRepository,
)
from src.source_assets.schema.source_asset_model import AssetScopeEnum
from src.users.user_model import UserModel

logger = logging.getLogger(__name__)

_MAX_ITERATION_STEPS = 6
_STEM_JOB_STALE_SECONDS = 900.0
_SUBPROCESS_HOLD_SECONDS = 25.0
_SAVE_WAIT_POLL_SECONDS = 1.5
_SAVE_WAIT_MAX_SECONDS = 300.0
_NON_VOCAL_STEMS: tuple[str, ...] = (
    "drums",
    "bass",
    "guitar",
    "piano",
    "other",
)


def _default_gcs_service() -> GcsService:
    """Dependency factory avoiding ``bucket_name`` query parameter exposure."""
    return GcsService()


def _resolve_launcher(launcher: Any) -> StemJobLauncher:
    """Resolves a concrete ``StemJobLauncher`` even when constructed outside FastAPI."""
    if launcher is None or not hasattr(launcher, "start_job"):
        return get_default_stem_job_launcher()
    return launcher


def _mime_str(mime_obj: Any) -> str:
    return mime_obj.value if hasattr(mime_obj, "value") else str(mime_obj or "")


def _clean_display_stem(raw_name: str | None) -> str:
    text = (raw_name or "").strip()
    if not text:
        return ""
    if "." in text:
        stem = Path(text).stem.strip()
        if stem:
            return stem
    return text


@dataclass(frozen=True)
class _ResolvedAudioSource:
    """Validated reference or generated audio ready for stem processing."""

    gcs_uri: str
    source_name: str
    parent_item: MediaItemModel | None
    parent_index: int
    source_asset_link: SourceAssetLink | None
    source_media_link: SourceMediaItemLink | None


def _extract_parent_track_analysis(
    parent_item: MediaItemModel | None,
    parent_index: int,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Extracts normalized track metadata and prior iteration steps from a parent MediaItem."""
    if parent_item is None:
        return None, []

    normalized = normalize_audio_analysis(
        getattr(parent_item, "audio_analysis", None)
    )
    prior_steps: list[str] = []
    parent_track: dict[str, Any] | None = None

    if isinstance(normalized, dict):
        raw_steps = normalized.get("iteration_steps")
        if isinstance(raw_steps, list):
            prior_steps = [
                step.strip()
                for step in raw_steps
                if isinstance(step, str) and step.strip()
            ]
        tracks = normalized.get("tracks")
        if isinstance(tracks, list) and 0 <= parent_index < len(tracks):
            candidate = tracks[parent_index]
            if isinstance(candidate, dict):
                parent_track = candidate

    if not prior_steps:
        seed_prompt = (
            getattr(parent_item, "original_prompt", None)
            or getattr(parent_item, "prompt", None)
            or ""
        ).strip()
        if seed_prompt:
            prior_steps = [seed_prompt]

    return parent_track, prior_steps


def _build_stemmed_track_analysis(
    parent_track: dict[str, Any] | None,
    included_stems: Sequence[str],
    waveform: list[float] | None,
    duration_seconds: float | None,
) -> dict[str, Any]:
    """Adapts parent ``audio_analysis`` track metadata to the retained stems.

    Lyrics and vocal profile are preserved only when ``vocals`` is included so
    downstream Lyria iteration and the gallery lightbox stay faithful to the
    audible stem mix.
    """
    track: dict[str, Any] = {}
    if waveform is not None:
        track["waveform"] = waveform
    if duration_seconds is not None:
        track["duration_seconds"] = duration_seconds

    has_vocals = "vocals" in included_stems
    stem_labels = [STEM_LABELS[s] for s in included_stems if s in STEM_LABELS]

    if isinstance(parent_track, dict):
        structure = parent_track.get("structure")
        if isinstance(structure, list) and structure:
            track["structure"] = structure

        if has_vocals:
            lyrics = parent_track.get("lyrics")
            if isinstance(lyrics, str) and lyrics.strip():
                track["lyrics"] = lyrics

        raw_profile = parent_track.get("musical_profile")
        profile: dict[str, Any] = (
            dict(raw_profile) if isinstance(raw_profile, dict) else {}
        )
        profile["instrumentation"] = stem_labels
        if not has_vocals:
            profile.pop("vocalProfile", None)
            profile.pop("vocal_profile", None)
        track["musical_profile"] = profile
    else:
        track["musical_profile"] = {"instrumentation": stem_labels}

    return track


def _format_default_mix_title(
    source_name: str,
    selected_stems: Sequence[str],
) -> str:
    """Formats a concise gallery title describing the selected stems."""
    if tuple(selected_stems) == _NON_VOCAL_STEMS:
        return f"{source_name} (Instrumental)"
    if len(selected_stems) == len(UI_STEM_ORDER):
        return f"{source_name} (All Stems)"
    if len(selected_stems) == 1:
        return f"{source_name} ({STEM_LABELS[selected_stems[0]]} Only)"
    joined = " + ".join(STEM_LABELS[s] for s in selected_stems)
    return f"{source_name} ({joined})"


class AudioStemService:
    """Coordinates Cloud Run Job / subprocess stem separation and gallery saves."""

    def __init__(
        self,
        media_repo: MediaRepository = Depends(),
        source_asset_repo: SourceAssetRepository = Depends(),
        iam_signer_credentials: IamSignerCredentials = Depends(),
        gcs_service: GcsService = Depends(_default_gcs_service),
        stem_job_launcher: StemJobLauncher = Depends(
            get_default_stem_job_launcher
        ),
    ):
        self.media_repo = media_repo
        self.source_asset_repo = source_asset_repo
        self.iam_signer_credentials = iam_signer_credentials
        self.gcs_service = gcs_service
        self.stem_job_launcher = _resolve_launcher(stem_job_launcher)

    async def _resolve_audio_source(
        self,
        source: AssetReferenceDto,
        workspace_id: int,
    ) -> _ResolvedAudioSource:
        """Resolves and authorizes workspace access to a source_asset or media_item."""
        if source.type == "source_asset":
            asset = await self.source_asset_repo.get_by_id(source.id)
            if not asset or (
                asset.workspace_id != workspace_id
                and asset.scope != AssetScopeEnum.SYSTEM
            ):
                raise HTTPException(
                    status_code=404,
                    detail="Source audio asset was not found in this workspace.",
                )
            mime_val = _mime_str(asset.mime_type)
            if not asset.gcs_uri or not mime_val.startswith("audio/"):
                raise HTTPException(
                    status_code=422,
                    detail="Selected source asset is not a valid audio file.",
                )

            title_candidate = (
                asset.titles[0].strip()
                if asset.titles
                and isinstance(asset.titles[0], str)
                and asset.titles[0].strip()
                else ""
            )
            source_name = (
                title_candidate
                or _clean_display_stem(asset.original_filename)
                or f"Audio Asset #{asset.id}"
            )
            return _ResolvedAudioSource(
                gcs_uri=asset.gcs_uri,
                source_name=source_name,
                parent_item=None,
                parent_index=0,
                source_asset_link=SourceAssetLink(
                    asset_id=source.id,
                    role=AssetRoleEnum.AUDIO_REFERENCE,
                ),
                source_media_link=None,
            )

        if source.type == "media_item":
            media_index = source.index if source.index is not None else 0
            item = await self.media_repo.get_by_id(source.id)
            if not item or item.workspace_id != workspace_id:
                raise HTTPException(
                    status_code=404,
                    detail="Audio media item was not found in this workspace.",
                )
            mime_val = _mime_str(item.mime_type)
            if not mime_val.startswith("audio/"):
                raise HTTPException(
                    status_code=422,
                    detail="Selected media item is not an audio item.",
                )
            if not item.gcs_uris or not (0 <= media_index < len(item.gcs_uris)):
                raise HTTPException(
                    status_code=422,
                    detail=f"Audio track index {media_index} is out of bounds.",
                )

            source_name = ""
            if item.titles:
                if (
                    0 <= media_index < len(item.titles)
                    and isinstance(item.titles[media_index], str)
                    and item.titles[media_index].strip()
                ):
                    source_name = item.titles[media_index].strip()
                elif isinstance(item.titles[0], str) and item.titles[0].strip():
                    source_name = item.titles[0].strip()
            if not source_name and item.comment and item.comment.strip():
                source_name = item.comment.strip()
            if not source_name:
                fallback_prompt = (
                    item.original_prompt or item.prompt or ""
                ).strip()
                if fallback_prompt:
                    source_name = (
                        fallback_prompt[:48].rstrip() + "…"
                        if len(fallback_prompt) > 48
                        else fallback_prompt
                    )
            if not source_name:
                source_name = f"Audio #{item.id}"

            return _ResolvedAudioSource(
                gcs_uri=item.gcs_uris[media_index],
                source_name=source_name,
                parent_item=item,
                parent_index=media_index,
                source_asset_link=None,
                source_media_link=SourceMediaItemLink(
                    media_item_id=source.id,
                    media_index=media_index,
                    role=AssetRoleEnum.AUDIO_REFERENCE,
                ),
            )

        raise HTTPException(
            status_code=422,
            detail="source.type must be 'source_asset' or 'media_item'.",
        )

    async def _build_completed_response(
        self,
        manifest: dict[str, Any],
        source_name: str,
        *,
        cache_hit: bool,
    ) -> ExtractStemsResponseDto:
        """Signs the 6 cached stem URIs and builds a COMPLETED response DTO."""
        stems_map: dict[str, dict[str, Any]] = manifest["stems"]
        signed_urls = await asyncio.gather(
            *(
                asyncio.to_thread(
                    self.iam_signer_credentials.generate_presigned_url,
                    stems_map[stem_name]["gcs_uri"],
                )
                for stem_name in UI_STEM_ORDER
            )
        )
        preview_items = [
            StemPreviewItemDto(
                name=StemNameEnum(stem_name),
                label=STEM_LABELS[stem_name],
                gcs_uri=stems_map[stem_name]["gcs_uri"],
                presigned_url=signed_urls[idx],
                waveform=stems_map[stem_name].get("waveform"),
                duration_seconds=stems_map[stem_name].get("duration_seconds"),
                peak_level=float(stems_map[stem_name].get("peak_level") or 0.0),
                has_energy=bool(stems_map[stem_name].get("has_energy", True)),
            )
            for idx, stem_name in enumerate(UI_STEM_ORDER)
        ]
        return ExtractStemsResponseDto(
            status=StemJobStatusEnum.COMPLETED,
            cache_hit=cache_hit,
            source_name=source_name,
            duration_seconds=manifest.get("duration_seconds"),
            stems=preview_items,
        )

    async def _hold_if_supported(self, execution_ref: str) -> None:
        """Holds the request up to 25s so Cloud Run request-scoped CPU stays active."""
        clean_ref = (execution_ref or "").strip()
        if not clean_ref:
            return
        wait_fn = getattr(self.stem_job_launcher, "wait_for_completion", None)
        if callable(wait_fn):
            maybe_coro = wait_fn(clean_ref, _SUBPROCESS_HOLD_SECONDS)
            if inspect.isawaitable(maybe_coro):
                await maybe_coro

    async def _start_or_join_stem_job(
        self,
        source_gcs_uri: str,
        cache_key: str,
    ) -> dict[str, Any] | None:
        """Starts a subprocess / Cloud Run stem job unless one is already running.

        Returns a completed ``manifest`` dict immediately when the job finishes
        within the bounded long-poll window.
        """
        existing_job = await asyncio.to_thread(
            read_job_record_sync, self.gcs_service, cache_key
        )
        if isinstance(existing_job, dict) and (
            existing_job.get("status") == "processing"
        ):
            started_at = float(existing_job.get("started_at") or 0.0)
            age_sec = time.time() - started_at if started_at > 0 else 0.0
            exec_ref = str(existing_job.get("execution_ref") or "").strip()
            if age_sec < _STEM_JOB_STALE_SECONDS and exec_ref:
                exec_state = await self.stem_job_launcher.get_execution_state(
                    exec_ref
                )
                if exec_state.state == "running":
                    await self._hold_if_supported(exec_ref)
                    ready = await asyncio.to_thread(
                        read_cached_manifest_sync, self.gcs_service, cache_key
                    )
                    if ready is not None:
                        return ready
                    return None
                if exec_state.state == "succeeded":
                    ready = await asyncio.to_thread(
                        read_cached_manifest_sync, self.gcs_service, cache_key
                    )
                    if ready is not None:
                        return ready

        started_ts = time.time()
        await asyncio.to_thread(
            write_job_record_sync,
            self.gcs_service,
            cache_key,
            status="processing",
            source_gcs_uri=source_gcs_uri,
            started_at=started_ts,
        )
        try:
            execution_ref = await self.stem_job_launcher.start_job(
                source_gcs_uri=source_gcs_uri,
                cache_key=cache_key,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(
                "Failed to dispatch stem separation job for %s: %s",
                source_gcs_uri,
                exc,
                exc_info=True,
            )
            await asyncio.to_thread(
                write_job_record_sync,
                self.gcs_service,
                cache_key,
                status="failed",
                source_gcs_uri=source_gcs_uri,
                started_at=started_ts,
                error=str(exc) or "Failed to launch stem separation job.",
                error_code=502,
            )
            raise HTTPException(
                status_code=502,
                detail="Failed to launch audio stem separation job.",
            ) from exc

        manifest = await asyncio.to_thread(
            read_cached_manifest_sync, self.gcs_service, cache_key
        )
        if manifest is not None:
            return manifest

        # Only persist 'processing' if the runner did not already finish/fail
        # synchronously during start_job (e.g. in-process test launchers).
        latest_job = await asyncio.to_thread(
            read_job_record_sync, self.gcs_service, cache_key
        )
        if not isinstance(latest_job, dict) or (
            latest_job.get("status") == "processing"
        ):
            await asyncio.to_thread(
                write_job_record_sync,
                self.gcs_service,
                cache_key,
                status="processing",
                source_gcs_uri=source_gcs_uri,
                execution_ref=execution_ref,
                started_at=started_ts,
            )
        elif latest_job.get("status") == "failed":
            raise HTTPException(
                status_code=int(latest_job.get("error_code") or 502),
                detail=str(
                    latest_job.get("error") or "Audio stem separation failed."
                ),
            )

        await self._hold_if_supported(execution_ref)
        manifest_after_hold = await asyncio.to_thread(
            read_cached_manifest_sync, self.gcs_service, cache_key
        )
        if manifest_after_hold is not None:
            return manifest_after_hold

        job_after_hold = await asyncio.to_thread(
            read_job_record_sync, self.gcs_service, cache_key
        )
        if (
            isinstance(job_after_hold, dict)
            and job_after_hold.get("status") == "failed"
        ):
            raise HTTPException(
                status_code=int(job_after_hold.get("error_code") or 502),
                detail=str(
                    job_after_hold.get("error")
                    or "Audio stem separation failed."
                ),
            )
        return None

    async def extract_stems(
        self,
        request_dto: ExtractStemsDto,
        user: UserModel,
    ) -> ExtractStemsResponseDto:
        """Returns cached stems immediately or dispatches isolated stem separation."""
        del user  # Workspace authorization is enforced by controller + source check
        resolved = await self._resolve_audio_source(
            request_dto.source,
            request_dto.workspace_id,
        )
        cache_key = compute_stem_cache_key(resolved.gcs_uri)
        cached = await asyncio.to_thread(
            read_cached_manifest_sync, self.gcs_service, cache_key
        )
        if cached is not None:
            return await self._build_completed_response(
                cached,
                resolved.source_name,
                cache_hit=True,
            )

        ready_manifest = await self._start_or_join_stem_job(
            resolved.gcs_uri, cache_key
        )
        if ready_manifest is not None:
            return await self._build_completed_response(
                ready_manifest,
                resolved.source_name,
                cache_hit=False,
            )

        return ExtractStemsResponseDto(
            status=StemJobStatusEnum.PROCESSING,
            cache_hit=False,
            source_name=resolved.source_name,
            stems=[],
        )

    async def get_stem_extraction_status(
        self,
        request_dto: ExtractStemsDto,
        user: UserModel,
    ) -> ExtractStemsResponseDto:
        """Polls the status of a stem separation job or returns ready stems."""
        del user
        resolved = await self._resolve_audio_source(
            request_dto.source,
            request_dto.workspace_id,
        )
        cache_key = compute_stem_cache_key(resolved.gcs_uri)
        cached = await asyncio.to_thread(
            read_cached_manifest_sync, self.gcs_service, cache_key
        )
        if cached is not None:
            return await self._build_completed_response(
                cached,
                resolved.source_name,
                cache_hit=False,
            )

        job_rec = await asyncio.to_thread(
            read_job_record_sync, self.gcs_service, cache_key
        )
        if job_rec is None:
            raise HTTPException(
                status_code=404,
                detail="No active stem separation job was found for this audio.",
            )

        if job_rec.get("status") == "failed":
            raise HTTPException(
                status_code=int(job_rec.get("error_code") or 502),
                detail=str(
                    job_rec.get("error") or "Audio stem separation failed."
                ),
            )

        exec_ref = str(job_rec.get("execution_ref") or "").strip()
        if exec_ref:
            await self._hold_if_supported(exec_ref)
            cached_after_hold = await asyncio.to_thread(
                read_cached_manifest_sync, self.gcs_service, cache_key
            )
            if cached_after_hold is not None:
                return await self._build_completed_response(
                    cached_after_hold,
                    resolved.source_name,
                    cache_hit=False,
                )
            exec_state = await self.stem_job_launcher.get_execution_state(
                exec_ref
            )
            if exec_state.state in ("failed", "succeeded"):
                refreshed_manifest = await asyncio.to_thread(
                    read_cached_manifest_sync, self.gcs_service, cache_key
                )
                if refreshed_manifest is not None:
                    return await self._build_completed_response(
                        refreshed_manifest,
                        resolved.source_name,
                        cache_hit=False,
                    )
                refreshed_job = await asyncio.to_thread(
                    read_job_record_sync, self.gcs_service, cache_key
                )
                if (
                    isinstance(refreshed_job, dict)
                    and refreshed_job.get("status") == "failed"
                ):
                    raise HTTPException(
                        status_code=int(refreshed_job.get("error_code") or 502),
                        detail=str(
                            refreshed_job.get("error")
                            or "Audio stem separation failed."
                        ),
                    )
                if exec_state.state == "failed":
                    err_detail = (
                        exec_state.error_message
                        or "Audio stem separation job failed."
                    )
                    await asyncio.to_thread(
                        write_job_record_sync,
                        self.gcs_service,
                        cache_key,
                        status="failed",
                        source_gcs_uri=resolved.gcs_uri,
                        execution_ref=exec_ref,
                        error=err_detail,
                        error_code=502,
                    )
                    raise HTTPException(status_code=502, detail=err_detail)
                raise HTTPException(
                    status_code=502,
                    detail="Audio stem job finished without producing stem outputs.",
                )

        started_at = float(job_rec.get("started_at") or 0.0)
        if started_at > 0 and (
            (time.time() - started_at) > _STEM_JOB_STALE_SECONDS
        ):
            raise HTTPException(
                status_code=504,
                detail="Audio stem separation timed out. Please retry.",
            )

        return ExtractStemsResponseDto(
            status=StemJobStatusEnum.PROCESSING,
            cache_hit=False,
            source_name=resolved.source_name,
            stems=[],
        )

    async def _ensure_stem_manifest(
        self,
        source_gcs_uri: str,
        source_ref: AssetReferenceDto,
        workspace_id: int,
        user: UserModel,
    ) -> dict[str, Any]:
        """Returns cached ``manifest.json`` or waits on an isolated stem job."""
        cache_key = compute_stem_cache_key(source_gcs_uri)
        cached = await asyncio.to_thread(
            read_cached_manifest_sync, self.gcs_service, cache_key
        )
        if cached is not None:
            return cached

        ready = await self._start_or_join_stem_job(source_gcs_uri, cache_key)
        if ready is not None:
            return ready

        deadline = time.monotonic() + _SAVE_WAIT_MAX_SECONDS
        poll_dto = ExtractStemsDto(workspace_id=workspace_id, source=source_ref)
        while time.monotonic() < deadline:
            await asyncio.sleep(_SAVE_WAIT_POLL_SECONDS)
            status_res = await self.get_stem_extraction_status(poll_dto, user)
            if status_res.status == StemJobStatusEnum.COMPLETED:
                manifest = await asyncio.to_thread(
                    read_cached_manifest_sync, self.gcs_service, cache_key
                )
                if manifest is not None:
                    return manifest

        raise HTTPException(
            status_code=504,
            detail="Timed out waiting for audio stem separation job to complete.",
        )

    def _build_combined_mix_sync(
        self,
        workspace_id: int,
        selected_names: Sequence[str],
        stems_map: dict[str, dict[str, Any]],
    ) -> tuple[str, list[float] | None, float | None]:
        """Downloads selected cached stems, mixes them, and uploads a permanent MP3."""
        uid_short = uuid.uuid4().hex[:12]
        blob_name = f"stemmed_audio/ws_{workspace_id}/{uid_short}_mix.mp3"

        if len(selected_names) == 1:
            only_stem = selected_names[0]
            entry = stems_map[only_stem]
            stem_bytes = self.gcs_service.download_bytes_from_gcs(
                entry["gcs_uri"]
            )
            if not stem_bytes:
                raise HTTPException(
                    status_code=502,
                    detail="Failed to read cached stem audio from Cloud Storage.",
                )
            uploaded_uri = self.gcs_service.upload_bytes_to_gcs(
                stem_bytes,
                blob_name,
                MimeTypeEnum.AUDIO_MPEG.value,
            )
            if not uploaded_uri:
                raise HTTPException(
                    status_code=502,
                    detail="Failed to upload stemmed audio to Cloud Storage.",
                )
            waveform = entry.get("waveform")
            duration_sec = entry.get("duration_seconds")
            if waveform is None or duration_sec is None:
                waveform, duration_sec = extract_audio_waveform_and_duration(
                    stem_bytes,
                    MimeTypeEnum.AUDIO_MPEG.value,
                )
            return uploaded_uri, waveform, duration_sec

        mixed_samples: np.ndarray | None = None
        for stem_name in selected_names:
            stem_bytes = self.gcs_service.download_bytes_from_gcs(
                stems_map[stem_name]["gcs_uri"]
            )
            if not stem_bytes:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to read cached '{stem_name}' stem from Cloud Storage.",
                )
            decoded = decode_audio_to_stereo_f32(stem_bytes)
            if mixed_samples is None:
                mixed_samples = decoded.astype(np.float32, copy=True)
            elif decoded.shape[1] <= mixed_samples.shape[1]:
                mixed_samples[:, : decoded.shape[1]] += decoded
            else:
                expanded = np.zeros(
                    (decoded.shape[0], decoded.shape[1]), dtype=np.float32
                )
                expanded[:, : mixed_samples.shape[1]] = mixed_samples
                expanded += decoded
                mixed_samples = expanded

        if mixed_samples is None:
            raise HTTPException(
                status_code=422,
                detail="At least one instrument stem must be selected.",
            )

        peak = float(np.max(np.abs(mixed_samples)))
        if peak > 0.99:
            mixed_samples *= np.float32(0.99 / peak)

        mixed_mp3 = encode_stereo_f32_to_mp3(mixed_samples, bitrate="256k")
        waveform, duration_sec = extract_audio_waveform_and_duration(
            mixed_mp3,
            MimeTypeEnum.AUDIO_MPEG.value,
        )
        uploaded_uri = self.gcs_service.upload_bytes_to_gcs(
            mixed_mp3,
            blob_name,
            MimeTypeEnum.AUDIO_MPEG.value,
        )
        if not uploaded_uri:
            raise HTTPException(
                status_code=502,
                detail="Failed to upload mixed stem audio to Cloud Storage.",
            )
        return uploaded_uri, waveform, duration_sec

    def _copy_separate_stems_sync(
        self,
        workspace_id: int,
        selected_names: Sequence[str],
        stems_map: dict[str, dict[str, Any]],
    ) -> list[tuple[str, list[float] | None, float | None]]:
        """Copies each selected cached stem to permanent gallery storage."""
        uid_short = uuid.uuid4().hex[:12]
        persisted: list[tuple[str, list[float] | None, float | None]] = []

        for idx, stem_name in enumerate(selected_names):
            entry = stems_map[stem_name]
            stem_bytes = self.gcs_service.download_bytes_from_gcs(
                entry["gcs_uri"]
            )
            if not stem_bytes:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to read cached '{stem_name}' stem from Cloud Storage.",
                )
            blob_name = f"stemmed_audio/ws_{workspace_id}/{uid_short}_{idx}_{stem_name}.mp3"
            uploaded_uri = self.gcs_service.upload_bytes_to_gcs(
                stem_bytes,
                blob_name,
                MimeTypeEnum.AUDIO_MPEG.value,
            )
            if not uploaded_uri:
                raise HTTPException(
                    status_code=502,
                    detail="Failed to upload separated stem audio to Cloud Storage.",
                )
            waveform = entry.get("waveform")
            duration_sec = entry.get("duration_seconds")
            if waveform is None or duration_sec is None:
                waveform, duration_sec = extract_audio_waveform_and_duration(
                    stem_bytes,
                    MimeTypeEnum.AUDIO_MPEG.value,
                )
            persisted.append((uploaded_uri, waveform, duration_sec))

        return persisted

    async def save_stem_mix(
        self,
        request_dto: SaveStemMixDto,
        user: UserModel,
    ) -> MediaItemResponse:
        """Persists selected stems as a completed gallery ``MediaItem``."""
        start_time = time.monotonic()
        folder_id = await resolve_output_folder_id(
            self.media_repo.db,
            request_dto.workspace_id,
            user,
            request_dto.folder_id,
        )
        resolved = await self._resolve_audio_source(
            request_dto.source,
            request_dto.workspace_id,
        )
        manifest = await self._ensure_stem_manifest(
            resolved.gcs_uri,
            request_dto.source,
            request_dto.workspace_id,
            user,
        )
        stems_map: dict[str, dict[str, Any]] = manifest["stems"]

        requested_set = {stem.value for stem in request_dto.selected_stems}
        selected_names = [s for s in UI_STEM_ORDER if s in requested_set]
        if not selected_names:
            raise HTTPException(
                status_code=422,
                detail="At least one instrument stem must be selected.",
            )

        custom_title = (request_dto.file_name or "").strip()
        base_title = custom_title or _format_default_mix_title(
            resolved.source_name,
            selected_names,
        )
        stem_label_list = ", ".join(STEM_LABELS[s] for s in selected_names)
        stem_summary_step = f"Isolated stems: {stem_label_list}"

        parent_track, prior_steps = _extract_parent_track_analysis(
            resolved.parent_item,
            resolved.parent_index,
        )
        iteration_steps = [*prior_steps, stem_summary_step][
            -_MAX_ITERATION_STEPS:
        ]

        if request_dto.save_mode == StemSaveModeEnum.COMBINED:
            uploaded_uri, waveform, duration_sec = await asyncio.to_thread(
                self._build_combined_mix_sync,
                request_dto.workspace_id,
                selected_names,
                stems_map,
            )
            gcs_uris = [uploaded_uri]
            titles = [base_title]
            descriptions = [
                f"{stem_label_list} mix isolated from {resolved.source_name}."
            ]
            tracks_analysis = [
                _build_stemmed_track_analysis(
                    parent_track,
                    selected_names,
                    waveform,
                    duration_sec,
                )
            ]
            item_duration = duration_sec
        else:
            persisted_tracks = await asyncio.to_thread(
                self._copy_separate_stems_sync,
                request_dto.workspace_id,
                selected_names,
                stems_map,
            )
            title_prefix = custom_title or resolved.source_name
            gcs_uris = [uri for uri, _, _ in persisted_tracks]
            titles = [
                f"{title_prefix} — {STEM_LABELS[stem_name]}"
                for stem_name in selected_names
            ]
            descriptions = [
                f"Isolated {STEM_LABELS[stem_name].lower()} stem from {resolved.source_name}."
                for stem_name in selected_names
            ]
            tracks_analysis = [
                _build_stemmed_track_analysis(
                    parent_track,
                    [stem_name],
                    persisted_tracks[idx][1],
                    persisted_tracks[idx][2],
                )
                for idx, stem_name in enumerate(selected_names)
            ]
            item_duration = persisted_tracks[0][2] if persisted_tracks else None

        parent_prompt = (
            (
                getattr(resolved.parent_item, "original_prompt", None)
                or getattr(resolved.parent_item, "prompt", None)
                or ""
            ).strip()
            if resolved.parent_item is not None
            else ""
        )
        prompt_text = (
            f"{parent_prompt} [{stem_summary_step}]"
            if parent_prompt
            else f"{stem_summary_step} ({resolved.source_name})"
        )

        elapsed = round(max(0.01, time.monotonic() - start_time), 2)
        media_to_create = MediaItemModel(
            workspace_id=request_dto.workspace_id,
            folder_id=folder_id,
            user_email=user.email,
            user_id=user.id,
            mime_type=MimeTypeEnum.AUDIO_MPEG,
            model=GenerationModelEnum.HTDEMUCS_6S,
            aspect_ratio=AspectRatioEnum.RATIO_16_9,
            status=JobStatusEnum.COMPLETED,
            prompt=prompt_text,
            original_prompt=parent_prompt or prompt_text,
            num_media=len(gcs_uris),
            generation_time=elapsed,
            gcs_uris=gcs_uris,
            duration_seconds=item_duration,
            titles=titles,
            descriptions=descriptions,
            comment=base_title,
            source_assets=(
                [resolved.source_asset_link]
                if resolved.source_asset_link is not None
                else None
            ),
            source_media_items=(
                [resolved.source_media_link]
                if resolved.source_media_link is not None
                else None
            ),
            audio_analysis={
                "tracks": tracks_analysis,
                "iteration_steps": iteration_steps,
            },
            raw_data={
                "stem_separation": {
                    "model": GenerationModelEnum.HTDEMUCS_6S.value,
                    "selected_stems": selected_names,
                    "save_mode": request_dto.save_mode.value,
                }
            },
        )
        saved_item = await self.media_repo.create(media_to_create)
        presigned_urls = await asyncio.gather(
            *(
                asyncio.to_thread(
                    self.iam_signer_credentials.generate_presigned_url,
                    uri,
                )
                for uri in saved_item.gcs_uris
            )
        )
        return MediaItemResponse(
            **saved_item.model_dump(),
            presigned_urls=list(presigned_urls),
        )
