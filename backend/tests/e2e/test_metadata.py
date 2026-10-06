# Copyright 2025 Google LLC
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
"""E2E tests for Automatic Metadata Generation (R2, R3)."""

import io
import asyncio
import pytest
from unittest.mock import patch
from PIL import Image as PILImage
from sqlalchemy import inspect, select
from src.database import engine, async_session_local
from src.common.schema.media_item_model import MediaItem, JobStatusEnum
from src.source_assets.schema.source_asset_model import SourceAsset


def get_valid_png_bytes() -> bytes:
    img = PILImage.new("RGB", (1, 1), color="red")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    return img_bytes.getvalue()


@pytest.mark.anyio
async def test_metadata_db_schema():
    """R2 Database schema check: inspect titles and descriptions in media_items and source_assets."""

    def inspect_columns(bind):
        ins = inspect(bind)
        columns_media = {
            c["name"]: str(c["type"]) for c in ins.get_columns("media_items")
        }
        columns_assets = {
            c["name"]: str(c["type"]) for c in ins.get_columns("source_assets")
        }
        return columns_media, columns_assets

    async with engine.connect() as conn:
        columns_media, columns_assets = await conn.run_sync(inspect_columns)

    # Check media_items table
    assert "titles" in columns_media
    assert (
        "ARRAY" in columns_media["titles"].upper()
        or "VARCHAR[]" in columns_media["titles"].upper()
        or "TEXT[]" in columns_media["titles"].upper()
    )
    assert "descriptions" in columns_media
    assert (
        "ARRAY" in columns_media["descriptions"].upper()
        or "VARCHAR[]" in columns_media["descriptions"].upper()
        or "TEXT[]" in columns_media["descriptions"].upper()
    )

    # Check source_assets table
    assert "titles" in columns_assets
    assert (
        "ARRAY" in columns_assets["titles"].upper()
        or "VARCHAR[]" in columns_assets["titles"].upper()
        or "TEXT[]" in columns_assets["titles"].upper()
    )
    assert "descriptions" in columns_assets
    assert (
        "ARRAY" in columns_assets["descriptions"].upper()
        or "VARCHAR[]" in columns_assets["descriptions"].upper()
        or "TEXT[]" in columns_assets["descriptions"].upper()
    )


@pytest.mark.anyio
async def test_metadata_source_asset_upload(e2e_client, e2e_test_workspace):
    """R3: Upload source asset, verify AI-generated titles and descriptions."""
    png_data = get_valid_png_bytes()
    files = {"file": ("creative_logo.png", png_data, "image/png")}
    data = {
        "workspaceId": e2e_test_workspace,
        "metadata_generation_model": "gemini-3.5-flash",
    }
    resp = e2e_client.post("/api/source_assets/upload", files=files, data=data)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["titles"] == ["Mock Media Title"]
    assert res_data["descriptions"] == ["Mock Media Description"]

    # Verify directly in the database
    async with async_session_local() as session:
        query = select(SourceAsset).where(SourceAsset.id == res_data["id"])
        result = await session.execute(query)
        db_asset = result.scalar_one()
        assert db_asset.titles == ["Mock Media Title"]
        assert db_asset.descriptions == ["Mock Media Description"]


@pytest.mark.anyio
async def test_metadata_async_generation(e2e_client, e2e_test_workspace):
    """R3: Trigger asynchronous generation (Imagen, Veo, Audio) and check DB metadata on completion."""
    # 1. Trigger Video (Veo) Generation
    video_payload = {
        "prompt": "a beautiful flying dragon",
        "workspace_id": e2e_test_workspace,
        "metadata_generation_model": "gemini-3.5-flash",
        "generation_model": "veo-3.1-generate-001",
        "aspect_ratio": "16:9",
        "duration_seconds": 8,
    }
    video_resp = e2e_client.post(
        "/api/videos/generate-videos", json=video_payload
    )
    assert video_resp.status_code == 200
    video_item = video_resp.json()
    video_id = video_item["id"]

    # 2. Trigger Audio Generation
    audio_payload = {
        "prompt": "happy upbeat background corporate music",
        "workspace_id": e2e_test_workspace,
        "metadata_generation_model": "gemini-3.5-flash",
        "model": "lyria-002",
    }
    audio_resp = e2e_client.post("/api/audios/generate", json=audio_payload)
    assert audio_resp.status_code == 200
    audio_item = audio_resp.json()
    audio_id = audio_item["id"]

    # 3. Trigger Image (Imagen) Generation
    image_payload = {
        "prompt": "a futuristic city sketch",
        "workspace_id": e2e_test_workspace,
        "metadata_generation_model": "gemini-3.5-flash",
        "generation_model": "gemini-3.1-flash-image-preview",
        "aspect_ratio": "1:1",
    }
    image_resp = e2e_client.post(
        "/api/images/generate-images", json=image_payload
    )
    assert image_resp.status_code == 200
    image_item = image_resp.json()
    image_id = image_item["id"]

    # Poll database for completion (up to 5 seconds)
    async def wait_for_completion(item_id):
        for _ in range(50):
            async with async_session_local() as session:
                query = select(MediaItem).where(MediaItem.id == item_id)
                res = await session.execute(query)
                item = res.scalar_one()
                if item.status in (
                    JobStatusEnum.COMPLETED,
                    JobStatusEnum.FAILED,
                ):
                    return item
            await asyncio.sleep(0.1)
        raise TimeoutError(f"Job {item_id} did not complete in time")

    db_video = await wait_for_completion(video_id)
    assert db_video.status == JobStatusEnum.COMPLETED
    assert db_video.titles == ["Mock Media Title"]
    assert db_video.descriptions == ["Mock Media Description"]

    db_audio = await wait_for_completion(audio_id)
    assert db_audio.status == JobStatusEnum.COMPLETED
    assert db_audio.titles == ["Mock Media Title"]
    assert db_audio.descriptions == ["Mock Media Description"]

    db_image = await wait_for_completion(image_id)
    assert db_image.status == JobStatusEnum.COMPLETED
    # Image metadata generation is now supported in the backend
    assert db_image.titles == ["Mock Media Title"]
    assert db_image.descriptions == ["Mock Media Description"]


@pytest.mark.anyio
async def test_metadata_user_metadata_ignored(e2e_client, e2e_test_workspace):
    """R3: Verify that user-provided metadata parameters are ignored or overwritten by AI values."""
    png_data = get_valid_png_bytes()
    files = {"file": ("logo.png", png_data, "image/png")}
    data = {
        "workspaceId": e2e_test_workspace,
        "metadata_generation_model": "gemini-3.5-flash",
        "title": "My Custom Title",
        "description": "My Custom Description",
    }
    resp = e2e_client.post("/api/source_assets/upload", files=files, data=data)
    assert resp.status_code == 200
    res_data = resp.json()
    # Should still be overwritten by AI-generated values
    assert res_data["titles"] == ["Mock Media Title"]
    assert res_data["descriptions"] == ["Mock Media Description"]


@pytest.mark.anyio
async def test_metadata_fallbacks(e2e_client, e2e_test_workspace):
    """R3: When Gemini API metadata generation fails, verify that operations do not crash and fall back gracefully."""
    from src.multimodal.gemini_service import GeminiService

    # Mock generate_media_metadata to raise an exception
    with patch.object(
        GeminiService,
        "generate_media_metadata",
        side_effect=Exception("Gemini failure"),
    ):
        # 1. Source Asset Upload fallback
        png_data = get_valid_png_bytes()
        files = {"file": ("fallback_image.png", png_data, "image/png")}
        data = {
            "workspaceId": e2e_test_workspace,
            "metadata_generation_model": "gemini-3.5-flash",
        }
        resp = e2e_client.post(
            "/api/source_assets/upload", files=files, data=data
        )
        assert resp.status_code == 200
        res_data = resp.json()
        # Should be empty lists
        assert res_data["titles"] == []
        assert res_data["descriptions"] == []

        # 2. Async Video Generation fallback
        video_payload = {
            "prompt": "a beautiful waterfall",
            "workspace_id": e2e_test_workspace,
            "metadata_generation_model": "gemini-3.5-flash",
            "generation_model": "veo-3.1-generate-001",
            "aspect_ratio": "16:9",
            "duration_seconds": 8,
        }
        video_resp = e2e_client.post(
            "/api/videos/generate-videos", json=video_payload
        )
        assert video_resp.status_code == 200
        video_id = video_resp.json()["id"]

        # Wait for completion
        for _ in range(50):
            async with async_session_local() as session:
                query = select(MediaItem).where(MediaItem.id == video_id)
                res = await session.execute(query)
                item = res.scalar_one()
                if item.status in (
                    JobStatusEnum.COMPLETED,
                    JobStatusEnum.FAILED,
                ):
                    db_video = item
                    break
            await asyncio.sleep(0.1)

        assert db_video.status == JobStatusEnum.COMPLETED
        # Should fall back to empty lists for titles and descriptions
        assert db_video.titles == []
        assert db_video.descriptions == []
