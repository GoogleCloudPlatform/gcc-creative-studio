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
"""Unit tests for AudioStemService and stem DTOs."""

import json
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
import numpy as np
import pytest

from src.audios.audio_stem_service import AudioStemService
from src.audios.audio_stems import (
    HTDEMUCS_6S_SOURCES,
    SAMPLE_RATE,
    STEM_CACHE_SCHEMA_VERSION,
    UI_STEM_ORDER,
    encode_stereo_f32_to_mp3,
    encode_stereo_f32_to_wav,
)
from src.audios.dto.stem_audio_dto import (
    ExtractStemsDto,
    SaveStemMixDto,
    StemNameEnum,
    StemSaveModeEnum,
)
from src.common.base_dto import (
    AspectRatioEnum,
    AssetReferenceDto,
    GenerationModelEnum,
    MimeTypeEnum,
)
from src.common.schema.media_item_model import JobStatusEnum, MediaItemModel
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    SourceAssetModel,
)
from src.users.user_model import UserModel


class _InMemoryBlob:
    def __init__(self, store: dict[str, bytes], name: str):
        self._store = store
        self._name = name

    def exists(self) -> bool:
        return self._name in self._store

    def download_as_bytes(self) -> bytes:
        return self._store[self._name]

    def download_to_filename(self, filename: str) -> None:
        with open(filename, "wb") as out:
            out.write(self._store[self._name])


class _InMemoryGcsService:
    """In-memory stand-in for GcsService to test caching and uploads deterministically."""

    def __init__(self, bucket_name: str = "test-bucket"):
        self.bucket_name = bucket_name
        self.objects: dict[str, bytes] = {}
        self.bucket = MagicMock()
        self.bucket.blob.side_effect = lambda name: _InMemoryBlob(
            self.objects, name
        )

    def put_uri(self, gcs_uri: str, payload: bytes) -> None:
        prefix = f"gs://{self.bucket_name}/"
        assert gcs_uri.startswith(prefix)
        self.objects[gcs_uri[len(prefix) :]] = payload

    def download_bytes_from_gcs(self, gcs_uri: str) -> bytes | None:
        prefix = f"gs://{self.bucket_name}/"
        if not gcs_uri.startswith(prefix):
            return None
        return self.objects.get(gcs_uri[len(prefix) :])

    def upload_bytes_to_gcs(
        self, content_bytes: bytes, destination_blob_name: str, mime_type: str
    ) -> str:
        del mime_type
        self.objects[destination_blob_name] = content_bytes
        return f"gs://{self.bucket_name}/{destination_blob_name}"

    def upload_file_to_gcs(
        self, local_path: str, destination_blob_name: str, mime_type: str
    ) -> str:
        del mime_type
        with open(local_path, "rb") as f:
            self.objects[destination_blob_name] = f.read()
        return f"gs://{self.bucket_name}/{destination_blob_name}"


@pytest.fixture(name="test_user")
def fixture_test_user() -> UserModel:
    return UserModel(
        id=7,
        email="producer@example.com",
        name="Producer",
        roles=["user"],
    )


@pytest.fixture(name="sample_wav_bytes")
def fixture_sample_wav_bytes() -> bytes:
    t = np.linspace(0.0, 0.2, int(SAMPLE_RATE * 0.2), endpoint=False)
    wave_l = (0.3 * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)
    wave_r = (0.3 * np.cos(2 * np.pi * 220.0 * t)).astype(np.float32)
    return encode_stereo_f32_to_wav(np.stack([wave_l, wave_r], axis=0))


@pytest.fixture(name="fake_stem_arrays")
def fixture_fake_stem_arrays() -> dict[str, np.ndarray]:
    n = int(SAMPLE_RATE * 0.2)
    t = np.linspace(0.0, 0.2, n, endpoint=False)
    stems: dict[str, np.ndarray] = {}
    for idx, name in enumerate(HTDEMUCS_6S_SOURCES):
        amp = 0.0 if name == "piano" else 0.25
        sig = (amp * np.sin(2 * np.pi * (180 + idx * 60) * t)).astype(
            np.float32
        )
        stems[name] = np.stack([sig, sig], axis=0)
    return stems


@pytest.fixture(name="stem_service_bundle")
def fixture_stem_service_bundle():
    media_repo = MagicMock()
    media_repo.db = AsyncMock()
    media_repo.get_by_id = AsyncMock()

    async def _create_side_effect(model: MediaItemModel) -> MediaItemModel:
        return model.model_copy(update={"id": 901})

    media_repo.create = AsyncMock(side_effect=_create_side_effect)

    source_asset_repo = MagicMock()
    source_asset_repo.get_by_id = AsyncMock()

    signer = MagicMock()
    signer.generate_presigned_url.side_effect = (
        lambda uri: f"https://signed.example/{uri.split('/')[-1]}"
    )

    launcher = MagicMock()
    launcher.start_job = AsyncMock(
        return_value="projects/p/locations/r/jobs/j/executions/exec-1"
    )
    launcher.get_execution_state = AsyncMock()

    gcs = _InMemoryGcsService()
    service = AudioStemService(
        media_repo=media_repo,
        source_asset_repo=source_asset_repo,
        iam_signer_credentials=signer,
        gcs_service=gcs,
        stem_job_launcher=launcher,
    )
    return service, media_repo, source_asset_repo, gcs, launcher


def test_save_stem_mix_dto_deduplicates_stems_and_validates_source():
    dto = SaveStemMixDto(
        workspace_id=1,
        source=AssetReferenceDto(id=10, type="media_item", index=0),
        selected_stems=[
            StemNameEnum.DRUMS,
            StemNameEnum.BASS,
            StemNameEnum.DRUMS,
        ],
    )
    assert dto.selected_stems == [StemNameEnum.DRUMS, StemNameEnum.BASS]

    with pytest.raises(ValueError, match="positive integer"):
        ExtractStemsDto(
            workspace_id=1,
            source=AssetReferenceDto(id=0, type="source_asset"),
        )


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg binary not installed"
)
@pytest.mark.asyncio
async def test_extract_stems_job_dispatch_poll_and_cache_hit(
    stem_service_bundle,
    test_user: UserModel,
    sample_wav_bytes: bytes,
    fake_stem_arrays: dict[str, np.ndarray],
):
    from src.audios.audio_stems import EncodedStemResult, compute_stem_energy
    from src.audios.dto.stem_audio_dto import StemJobStatusEnum
    from src.audios.stem_job_launcher import ExecutionState
    from src.audios.stem_job_runner import run_job_from_args

    service, _, source_asset_repo, gcs, launcher = stem_service_bundle
    launcher.get_execution_state.return_value = ExecutionState(state="running")

    src_uri = "gs://test-bucket/uploads/demo_loop.wav"
    gcs.put_uri(src_uri, sample_wav_bytes)

    source_asset_repo.get_by_id.return_value = SourceAssetModel(
        id=44,
        workspace_id=5,
        user_id=test_user.id,
        gcs_uri=src_uri,
        original_filename="demo_loop.wav",
        mime_type=MimeTypeEnum.AUDIO_WAV,
        scope=AssetScopeEnum.PRIVATE,
    )

    req = ExtractStemsDto(
        workspace_id=5,
        source=AssetReferenceDto(id=44, type="source_asset"),
    )

    # 1. Cache miss dispatches Cloud Run Job and returns processing immediately
    start_res = await service.extract_stems(req, test_user)
    assert start_res.status == StemJobStatusEnum.PROCESSING
    assert start_res.cache_hit is False
    assert start_res.source_name == "demo_loop"
    assert start_res.stems == []
    assert launcher.start_job.call_count == 1

    # Duplicate /stems/extract while job is running joins existing execution
    join_res = await service.extract_stems(req, test_user)
    assert join_res.status == StemJobStatusEnum.PROCESSING
    assert launcher.start_job.call_count == 1

    # Poll while running -> still processing
    poll_running = await service.get_stem_extraction_status(req, test_user)
    assert poll_running.status == StemJobStatusEnum.PROCESSING

    # Simulate Cloud Run Job completing and writing stems + manifest.json
    fake_encoded = {
        name: EncodedStemResult(
            mp3_bytes=encode_stereo_f32_to_mp3(arr, bitrate="192k"),
            peak_level=compute_stem_energy(arr)[0],
            has_energy=compute_stem_energy(arr)[1],
            duration_seconds=0.2,
        )
        for name, arr in fake_stem_arrays.items()
    }
    with patch(
        "src.audios.stem_job_runner.separate_and_encode_stems_mp3",
        return_value=fake_encoded,
    ) as sep_mock:
        exit_code = run_job_from_args(source_gcs_uri=src_uri, gcs_service=gcs)
        assert exit_code == 0
        assert sep_mock.call_count == 1

    # Poll after job finishes -> returns completed with 6 signed stems
    poll_done = await service.get_stem_extraction_status(req, test_user)
    assert poll_done.status == StemJobStatusEnum.COMPLETED
    assert poll_done.cache_hit is False
    assert [s.name.value for s in poll_done.stems] == list(UI_STEM_ORDER)
    piano_stem = next(
        s for s in poll_done.stems if s.name == StemNameEnum.PIANO
    )
    assert piano_stem.has_energy is False

    # Subsequent /stems/extract hits GCS manifest immediately without job launch
    cached_res = await service.extract_stems(req, test_user)
    assert cached_res.status == StemJobStatusEnum.COMPLETED
    assert cached_res.cache_hit is True
    assert launcher.start_job.call_count == 1


@pytest.mark.asyncio
async def test_extract_stems_enforces_workspace_and_mime_guards(
    stem_service_bundle,
    test_user: UserModel,
):
    service, media_repo, source_asset_repo, _, _ = stem_service_bundle

    # Foreign private source_asset -> 404
    source_asset_repo.get_by_id.return_value = SourceAssetModel(
        id=11,
        workspace_id=99,
        user_id=99,
        gcs_uri="gs://test-bucket/foreign.mp3",
        mime_type=MimeTypeEnum.AUDIO_MPEG,
        scope=AssetScopeEnum.PRIVATE,
    )
    with pytest.raises(HTTPException) as exc_foreign:
        await service.extract_stems(
            ExtractStemsDto(
                workspace_id=5,
                source=AssetReferenceDto(id=11, type="source_asset"),
            ),
            test_user,
        )
    assert exc_foreign.value.status_code == 404

    # Image source_asset -> 422
    source_asset_repo.get_by_id.return_value = SourceAssetModel(
        id=12,
        workspace_id=5,
        user_id=test_user.id,
        gcs_uri="gs://test-bucket/pic.png",
        mime_type=MimeTypeEnum.IMAGE_PNG,
    )
    with pytest.raises(HTTPException) as exc_mime:
        await service.extract_stems(
            ExtractStemsDto(
                workspace_id=5,
                source=AssetReferenceDto(id=12, type="source_asset"),
            ),
            test_user,
        )
    assert exc_mime.value.status_code == 422

    # Out-of-bounds media_item index -> 422
    media_repo.get_by_id.return_value = MediaItemModel(
        id=20,
        workspace_id=5,
        user_email=test_user.email,
        mime_type=MimeTypeEnum.AUDIO_MPEG,
        model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
        aspect_ratio=AspectRatioEnum.RATIO_16_9,
        status=JobStatusEnum.COMPLETED,
        gcs_uris=["gs://test-bucket/track0.mp3"],
    )
    with pytest.raises(HTTPException) as exc_idx:
        await service.extract_stems(
            ExtractStemsDto(
                workspace_id=5,
                source=AssetReferenceDto(id=20, type="media_item", index=3),
            ),
            test_user,
        )
    assert exc_idx.value.status_code == 422


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg binary not installed"
)
@pytest.mark.asyncio
async def test_save_stem_mix_combined_and_separate_preserve_or_strip_lyrics(
    stem_service_bundle,
    test_user: UserModel,
    fake_stem_arrays: dict[str, np.ndarray],
):
    service, media_repo, _, gcs, _ = stem_service_bundle
    parent_uri = "gs://test-bucket/lyria/song_0.mp3"

    # Pre-populate cached stems in GCS
    from src.audios.audio_stems import compute_stem_cache_key

    cache_key = compute_stem_cache_key(parent_uri)
    stems_manifest = {}
    for stem_name in UI_STEM_ORDER:
        mp3_bytes = encode_stereo_f32_to_mp3(
            fake_stem_arrays[stem_name], bitrate="192k"
        )
        uri = gcs.upload_bytes_to_gcs(
            mp3_bytes,
            f"audio_stems_cache/{cache_key}/{stem_name}.mp3",
            "audio/mpeg",
        )
        stems_manifest[stem_name] = {
            "gcs_uri": uri,
            "waveform": [0.2, 0.8],
            "duration_seconds": 0.2,
            "peak_level": 0.25,
            "has_energy": True,
        }
    gcs.upload_bytes_to_gcs(
        json.dumps(
            {
                "schema_version": STEM_CACHE_SCHEMA_VERSION,
                "source_gcs_uri": parent_uri,
                "duration_seconds": 0.2,
                "stems": stems_manifest,
            }
        ).encode("utf-8"),
        f"audio_stems_cache/{cache_key}/manifest.json",
        "application/json",
    )

    media_repo.get_by_id.return_value = MediaItemModel(
        id=55,
        workspace_id=5,
        user_email=test_user.email,
        mime_type=MimeTypeEnum.AUDIO_MPEG,
        model=GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
        aspect_ratio=AspectRatioEnum.RATIO_16_9,
        status=JobStatusEnum.COMPLETED,
        prompt="Upbeat indie pop anthem",
        original_prompt="Upbeat indie pop anthem",
        titles=["Neon Skyline"],
        gcs_uris=[parent_uri],
        audio_analysis={
            "tracks": [
                {
                    "lyrics": "[Verse]\nCity lights tonight",
                    "structure": [{"name": "Verse", "duration": "0:15"}],
                    "musical_profile": {
                        "bpm": 122,
                        "keySignature": "C Major",
                        "vocalProfile": "Bright female lead",
                        "instrumentation": ["Vocals", "Drums", "Bass"],
                    },
                }
            ],
            "iteration_steps": ["Upbeat indie pop anthem"],
        },
    )

    with patch(
        "src.audios.audio_stem_service.resolve_output_folder_id",
        new=AsyncMock(return_value=19),
    ):
        # 1. Combined non-vocal mix -> strips lyrics & vocalProfile, keeps structure & BPM
        combined_res = await service.save_stem_mix(
            SaveStemMixDto(
                workspace_id=5,
                source=AssetReferenceDto(id=55, type="media_item", index=0),
                selected_stems=[StemNameEnum.DRUMS, StemNameEnum.BASS],
                save_mode=StemSaveModeEnum.COMBINED,
                folder_id=19,
            ),
            test_user,
        )

        assert combined_res.id == 901
        assert combined_res.folder_id == 19
        assert combined_res.model == GenerationModelEnum.HTDEMUCS_6S
        assert combined_res.num_media == 1
        assert combined_res.titles == ["Neon Skyline (Drums + Bass)"]
        track0 = combined_res.audio_analysis["tracks"][0]
        assert "lyrics" not in track0
        assert track0["structure"] == [{"name": "Verse", "duration": "0:15"}]
        assert track0["musical_profile"]["bpm"] == 122
        assert "vocalProfile" not in track0["musical_profile"]
        assert track0["musical_profile"]["instrumentation"] == ["Drums", "Bass"]
        assert combined_res.source_media_items[0].media_item_id == 55

        # 2. Separate mode including vocals -> vocals track keeps lyrics, drums track drops lyrics
        separate_res = await service.save_stem_mix(
            SaveStemMixDto(
                workspace_id=5,
                source=AssetReferenceDto(id=55, type="media_item", index=0),
                selected_stems=[StemNameEnum.DRUMS, StemNameEnum.VOCALS],
                save_mode=StemSaveModeEnum.SEPARATE,
            ),
            test_user,
        )

        assert separate_res.num_media == 2
        assert separate_res.titles == [
            "Neon Skyline — Vocals",
            "Neon Skyline — Drums",
        ]
        vocal_track = separate_res.audio_analysis["tracks"][0]
        drum_track = separate_res.audio_analysis["tracks"][1]
        assert "City lights tonight" in vocal_track["lyrics"]
        assert (
            vocal_track["musical_profile"]["vocalProfile"]
            == "Bright female lead"
        )
        assert "lyrics" not in drum_track
        assert "vocalProfile" not in drum_track["musical_profile"]
