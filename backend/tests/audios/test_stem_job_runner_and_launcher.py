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
"""Unit tests for Cloud Run / subprocess stem job runner and launcher."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
import pytest

from src.audios.audio_stem_service import AudioStemService
from src.audios.audio_stems import compute_stem_cache_key
from src.audios.dto.stem_audio_dto import ExtractStemsDto
from src.audios.stem_job_launcher import (
    CloudRunStemJobLauncher,
    ExecutionState,
    LocalSubprocessStemJobLauncher,
    _parse_cloud_run_resource_state,
    get_default_stem_job_launcher,
)
from src.audios.stem_job_runner import (
    download_model_from_gcs_sync,
    main as runner_main,
    read_job_record_sync,
    run_job_from_args,
    upload_model_to_gcs_sync,
    write_job_record_sync,
)
from src.common.base_dto import AssetReferenceDto, MimeTypeEnum
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    SourceAssetModel,
)
from src.users.user_model import UserModel
from tests.audios.test_audio_stem_service import _InMemoryGcsService


def test_parse_cloud_run_resource_state_handles_executions_and_operations():
    # 1. Running LRO Operation
    assert _parse_cloud_run_resource_state({"done": False}) == ExecutionState(
        state="running"
    )

    # 2. Failed LRO Operation
    op_fail = _parse_cloud_run_resource_state(
        {"done": True, "error": {"message": "Quota exceeded"}}
    )
    assert op_fail.state == "failed"
    assert op_fail.error_message == "Quota exceeded"

    # 3. Completed LRO wrapping an Execution
    op_ok = _parse_cloud_run_resource_state(
        {
            "done": True,
            "response": {
                "taskCount": 1,
                "succeededCount": 1,
                "conditions": [
                    {"type": "Completed", "state": "CONDITION_SUCCEEDED"}
                ],
            },
        }
    )
    assert op_ok == ExecutionState(state="succeeded")

    # 4. Failed Execution condition
    exec_fail = _parse_cloud_run_resource_state(
        {
            "taskCount": 1,
            "failedCount": 1,
            "conditions": [
                {
                    "type": "Completed",
                    "state": "CONDITION_FAILED",
                    "message": "Container exited with code 137",
                }
            ],
        }
    )
    assert exec_fail.state == "failed"
    assert "137" in (exec_fail.error_message or "")

    # 5. In-progress Execution
    exec_running = _parse_cloud_run_resource_state(
        {"taskCount": 1, "runningCount": 1, "conditions": []}
    )
    assert exec_running == ExecutionState(state="running")


@pytest.mark.asyncio
async def test_cloud_run_stem_job_launcher_run_and_status():
    launcher = CloudRunStemJobLauncher(
        project_id="my-proj",
        region="europe-west1",
        job_name="cs-dev-stems-job",
    )

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "name": "projects/my-proj/locations/europe-west1/operations/op-1",
        "metadata": {
            "name": (
                "projects/my-proj/locations/europe-west1/"
                "jobs/cs-dev-stems-job/executions/exec-99"
            )
        },
    }

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = {
        "taskCount": 1,
        "succeededCount": 1,
        "completionTime": "2026-11-10T21:00:00Z",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_post_resp
    mock_client.get.return_value = mock_get_resp

    with (
        patch(
            "src.audios.stem_job_launcher._fetch_cloud_platform_bearer_token_sync",
            return_value="fake-token",
        ),
        patch(
            "src.audios.stem_job_launcher.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        exec_ref = await launcher.start_job(
            "gs://b/track.mp3", "cachekey1234567890123456"
        )
        assert exec_ref.endswith("/executions/exec-99")
        post_kwargs = mock_client.post.call_args.kwargs
        env_list = post_kwargs["json"]["overrides"]["containerOverrides"][0][
            "env"
        ]
        assert {"name": "STEM_SOURCE_GCS_URI", "value": "gs://b/track.mp3"} in (
            env_list
        )
        assert {
            "name": "STEM_CACHE_KEY",
            "value": "cachekey1234567890123456",
        } in env_list

        state = await launcher.get_execution_state(exec_ref)
        assert state.state == "succeeded"

    # Unconfigured launcher raises RuntimeError
    bad_launcher = CloudRunStemJobLauncher(
        project_id="", region="us-central1", job_name=""
    )
    with pytest.raises(RuntimeError, match="not configured"):
        await bad_launcher.start_job("gs://b/a.mp3", "k")


@pytest.mark.asyncio
async def test_local_subprocess_stem_job_launcher_lifecycle():
    launcher = LocalSubprocessStemJobLauncher()

    fake_proc = MagicMock()
    fake_proc.pid = 43210
    fake_proc.returncode = None

    done_event = asyncio.Event()

    async def _fake_communicate():
        await done_event.wait()
        return b"", b"Fatal audio decode error\n"

    fake_proc.communicate = _fake_communicate

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ):
        ref = await launcher.start_job("gs://b/in.wav", "key001")
        assert ref.startswith("local:43210:")
        running_state = await launcher.get_execution_state(ref)
        assert running_state.state == "running"

        # Bounded hold times out cleanly while process is still running
        await launcher.wait_for_completion(ref, timeout_seconds=0.01)

        fake_proc.returncode = 1
        done_event.set()
        await launcher.wait_for_completion(ref, timeout_seconds=1.0)

        failed_state = await launcher.get_execution_state(ref)
        assert failed_state.state == "failed"
        assert "Fatal audio decode error" in (failed_state.error_message or "")

    assert (await launcher.get_execution_state("local:unknown")).state == (
        "unknown"
    )


def test_runner_records_validation_and_runtime_errors_and_gcs_model_helpers(
    tmp_path: Path,
):
    gcs = _InMemoryGcsService()
    src_uri = "gs://test-bucket/bad.mp3"
    cache_key = compute_stem_cache_key(src_uri)

    # Missing source blob -> 502 error recorded in job.json
    rc_missing = run_job_from_args(
        source_gcs_uri=src_uri, cache_key=cache_key, gcs_service=gcs
    )
    assert rc_missing == 1
    rec_502 = read_job_record_sync(gcs, cache_key)
    assert rec_502 is not None
    assert rec_502["status"] == "failed"
    assert rec_502["error_code"] == 502

    # ValueError (e.g. >300s duration) -> 422 error recorded in job.json
    gcs.put_uri(src_uri, b"corrupt-audio")
    with patch(
        "src.audios.stem_job_runner.separate_and_encode_stems_mp3",
        side_effect=ValueError("Audio is 400.0s long"),
    ):
        rc_val = run_job_from_args(
            source_gcs_uri=src_uri, cache_key=cache_key, gcs_service=gcs
        )
    assert rc_val == 1
    rec_422 = read_job_record_sync(gcs, cache_key)
    assert rec_422 is not None
    assert rec_422["status"] == "failed"
    assert rec_422["error_code"] == 422
    assert "400.0s" in rec_422["error"]

    # Empty URI -> exit code 2 via CLI main()
    assert runner_main(["--source-gcs-uri", "   "]) == 2

    # GCS model mirror upload/download helpers
    model_src = tmp_path / "weights.onnx"
    model_src.write_bytes(b"onnx-weights")
    dest_file = tmp_path / "dl" / "weights.onnx"
    assert download_model_from_gcs_sync(gcs, dest_file) is False
    upload_model_to_gcs_sync(gcs, model_src)
    assert download_model_from_gcs_sync(gcs, dest_file) is True
    assert dest_file.read_bytes() == b"onnx-weights"


@pytest.mark.asyncio
async def test_status_surfaces_job_failures_and_crashes():
    media_repo = MagicMock()
    media_repo.db = AsyncMock()
    source_asset_repo = MagicMock()
    src_uri = "gs://test-bucket/track.mp3"
    cache_key = compute_stem_cache_key(src_uri)
    source_asset_repo.get_by_id = AsyncMock(
        return_value=SourceAssetModel(
            id=9,
            workspace_id=2,
            user_id=1,
            gcs_uri=src_uri,
            mime_type=MimeTypeEnum.AUDIO_MPEG,
            scope=AssetScopeEnum.PRIVATE,
        )
    )
    launcher = MagicMock()
    launcher.start_job = AsyncMock(
        return_value="projects/p/locations/r/jobs/j/executions/e1"
    )
    launcher.get_execution_state = AsyncMock(
        return_value=ExecutionState(
            state="failed", error_message="OOMKilled (exit 137)"
        )
    )
    gcs = _InMemoryGcsService()
    service = AudioStemService(
        media_repo=media_repo,
        source_asset_repo=source_asset_repo,
        iam_signer_credentials=MagicMock(),
        gcs_service=gcs,
        stem_job_launcher=launcher,
    )
    user = UserModel(id=1, email="u@example.com", name="U", roles=["user"])
    dto = ExtractStemsDto(
        workspace_id=2,
        source=AssetReferenceDto(id=9, type="source_asset"),
    )

    # Status before job started -> 404
    with pytest.raises(HTTPException) as exc_404:
        await service.get_stem_extraction_status(dto, user)
    assert exc_404.value.status_code == 404

    # Job still marked 'processing' in GCS, but Cloud Run reports OOM crash -> 502
    write_job_record_sync(
        gcs,
        cache_key,
        status="processing",
        source_gcs_uri=src_uri,
        execution_ref="projects/p/locations/r/jobs/j/executions/e1",
    )
    with pytest.raises(HTTPException) as exc_crash:
        await service.get_stem_extraction_status(dto, user)
    assert exc_crash.value.status_code == 502
    assert "OOMKilled" in exc_crash.value.detail


def test_default_launcher_selection_respects_config(
    monkeypatch: pytest.MonkeyPatch,
):
    from src.config.config_service import ConfigService, config_service

    fresh_cfg = ConfigService(PROJECT_ID="demo-proj", REGION="europe-west4")
    assert fresh_cfg.AUDIO_STEM_JOB_NAME == "creative-studio-stems-job"
    assert fresh_cfg.AUDIO_STEM_JOB_REGION == "europe-west4"

    monkeypatch.setattr(config_service, "USE_LOCAL_STEM_RUNNER", True)
    assert isinstance(
        get_default_stem_job_launcher(), LocalSubprocessStemJobLauncher
    )

    monkeypatch.setattr(config_service, "USE_LOCAL_STEM_RUNNER", False)
    monkeypatch.setattr(config_service, "PROJECT_ID", "proj")
    monkeypatch.setattr(config_service, "AUDIO_STEM_JOB_REGION", "europe-west1")
    cloud_strict = get_default_stem_job_launcher()
    assert isinstance(cloud_strict, CloudRunStemJobLauncher)
    assert cloud_strict.region == "europe-west1"
    assert cloud_strict.allow_local_fallback is False

    monkeypatch.setattr(config_service, "USE_LOCAL_STEM_RUNNER", None)
    monkeypatch.setattr(config_service, "ENVIRONMENT", "production")
    cloud_auto = get_default_stem_job_launcher()
    assert isinstance(cloud_auto, CloudRunStemJobLauncher)
    assert cloud_auto.allow_local_fallback is True


@pytest.mark.asyncio
async def test_cloud_launcher_fallback_vs_strict_mode():
    mock_403 = MagicMock()
    mock_403.status_code = 403
    mock_403.text = "Permission denied"

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_403

    with (
        patch(
            "src.audios.stem_job_launcher._fetch_cloud_platform_bearer_token_sync",
            return_value="tok",
        ),
        patch(
            "src.audios.stem_job_launcher.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        strict = CloudRunStemJobLauncher(
            project_id="p",
            region="us-central1",
            job_name="creative-studio-stems-job",
            allow_local_fallback=False,
        )
        with pytest.raises(RuntimeError, match="HTTP 403"):
            await strict.start_job("gs://b/a.mp3", "k1")

        auto = CloudRunStemJobLauncher(
            project_id="p",
            region="us-central1",
            job_name="creative-studio-stems-job",
            allow_local_fallback=True,
        )
        auto._fallback_launcher.start_job = AsyncMock(
            return_value="local:999:abcd"
        )
        ref = await auto.start_job("gs://b/a.mp3", "k2")
        assert ref == "local:999:abcd"


@pytest.mark.asyncio
async def test_launch_error_stale_timeout_and_single_stem_fast_copy():
    import json
    import time

    from src.audios.audio_stems import STEM_CACHE_SCHEMA_VERSION, UI_STEM_ORDER
    from src.audios.dto.stem_audio_dto import (
        SaveStemMixDto,
        StemNameEnum,
        StemSaveModeEnum,
    )

    media_repo = MagicMock()
    media_repo.db = AsyncMock()
    media_repo.create = AsyncMock(
        side_effect=lambda m: m.model_copy(update={"id": 888})
    )
    src_uri = "gs://test-bucket/solo.mp3"
    cache_key = compute_stem_cache_key(src_uri)
    source_asset_repo = MagicMock()
    source_asset_repo.get_by_id = AsyncMock(
        return_value=SourceAssetModel(
            id=15,
            workspace_id=3,
            user_id=1,
            gcs_uri=src_uri,
            titles=["Solo Demo"],
            mime_type=MimeTypeEnum.AUDIO_MPEG,
            scope=AssetScopeEnum.SYSTEM,
        )
    )

    launcher = MagicMock()
    launcher.start_job = AsyncMock(side_effect=RuntimeError("IAM denied"))
    launcher.get_execution_state = AsyncMock(
        return_value=ExecutionState(state="running")
    )
    signer = MagicMock()
    signer.generate_presigned_url.return_value = "https://signed.example/s.mp3"

    gcs = _InMemoryGcsService()
    service = AudioStemService(
        media_repo=media_repo,
        source_asset_repo=source_asset_repo,
        iam_signer_credentials=signer,
        gcs_service=gcs,
        stem_job_launcher=launcher,
    )
    user = UserModel(id=1, email="u@example.com", name="U", roles=["user"])
    dto = ExtractStemsDto(
        workspace_id=3,
        source=AssetReferenceDto(id=15, type="source_asset"),
    )

    # 1. Launcher error -> 502 and records failed job.json
    with pytest.raises(HTTPException) as exc_launch:
        await service.extract_stems(dto, user)
    assert exc_launch.value.status_code == 502

    # 2. Stale processing job (>900s) -> 504
    write_job_record_sync(
        gcs,
        cache_key,
        status="processing",
        source_gcs_uri=src_uri,
        execution_ref="projects/p/locations/r/jobs/j/executions/e2",
        started_at=time.time() - 1200.0,
    )
    with pytest.raises(HTTPException) as exc_stale:
        await service.get_stem_extraction_status(dto, user)
    assert exc_stale.value.status_code == 504

    # 3. Single-stem COMBINED save fast-copies cached stem bytes without re-encoding
    stems_manifest = {}
    for stem_name in UI_STEM_ORDER:
        uri = gcs.upload_bytes_to_gcs(
            b"fake-mp3-bytes",
            f"audio_stems_cache/{cache_key}/{stem_name}.mp3",
            "audio/mpeg",
        )
        stems_manifest[stem_name] = {
            "gcs_uri": uri,
            "waveform": [0.3, 0.6],
            "duration_seconds": 4.0,
            "peak_level": 0.5,
            "has_energy": True,
        }
    gcs.upload_bytes_to_gcs(
        json.dumps(
            {
                "schema_version": STEM_CACHE_SCHEMA_VERSION,
                "source_gcs_uri": src_uri,
                "duration_seconds": 4.0,
                "stems": stems_manifest,
            }
        ).encode("utf-8"),
        f"audio_stems_cache/{cache_key}/manifest.json",
        "application/json",
    )

    with patch(
        "src.audios.audio_stem_service.resolve_output_folder_id",
        new=AsyncMock(return_value=None),
    ):
        saved = await service.save_stem_mix(
            SaveStemMixDto(
                workspace_id=3,
                source=AssetReferenceDto(id=15, type="source_asset"),
                selected_stems=[StemNameEnum.VOCALS],
                save_mode=StemSaveModeEnum.COMBINED,
            ),
            user,
        )
    assert saved.id == 888
    assert saved.titles == ["Solo Demo (Vocals Only)"]
