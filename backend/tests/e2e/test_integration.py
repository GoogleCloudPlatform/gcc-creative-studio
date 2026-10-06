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
"""E2E integration tests for GCC Creative Studio."""

import io
import asyncio
import pytest
from PIL import Image as PILImage
from sqlalchemy import select, delete
from src.database import async_session_local
from src.common.schema.media_item_model import (
    MediaItem,
    JobStatusEnum,
    AssetRoleEnum,
)
from src.source_assets.schema.source_asset_model import SourceAsset
from src.workspaces.schema.workspace_model import (
    Workspace,
    WorkspaceMemberAssociation,
)


def get_valid_png_bytes() -> bytes:
    img = PILImage.new("RGB", (1, 1), color="blue")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    return img_bytes.getvalue()


async def wait_for_completion(item_id, timeout_seconds=10):
    for _ in range(int(timeout_seconds * 10)):
        async with async_session_local() as session:
            query = select(MediaItem).where(MediaItem.id == item_id)
            res = await session.execute(query)
            item = res.scalar_one_or_none()
            if item and item.status in (
                JobStatusEnum.COMPLETED,
                JobStatusEnum.FAILED,
            ):
                return item
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Job {item_id} did not complete in time")


@pytest.mark.anyio
async def test_integration_upload_brand_asset_to_multimodal(
    e2e_client, e2e_test_workspace
):
    """Tier 3: Upload brand asset, retrieve its ID, and pass it to multimodal generation."""
    # 1. Upload logo
    png_data = get_valid_png_bytes()
    files = {"file": ("brand_logo.png", png_data, "image/png")}
    data = {
        "workspaceId": e2e_test_workspace,
        "metadata_generation_model": "gemini-3.5-flash",
    }
    upload_resp = e2e_client.post(
        "/api/source_assets/upload", files=files, data=data
    )
    assert upload_resp.status_code == 200
    asset_id = upload_resp.json()["id"]

    # 2. Call multimodal generation referencing the uploaded asset
    payload = {
        "workspace_id": e2e_test_workspace,
        "prompt": "Analyze this brand logo",
        "source_asset_ids": [asset_id],
        "model": "gemini-3.5-flash",
    }
    resp = e2e_client.post("/api/gemini/multimodal-generation", json=payload)
    assert resp.status_code == 200

    assert resp.json()["text"] == "Mock Multimodal Generated Content Text"


@pytest.mark.anyio
async def test_integration_generate_image_to_multimodal(
    e2e_client, e2e_test_workspace
):
    """Tier 3: Generate image, retrieve its ID, use it to run multimodal generation."""
    # 1. Generate image
    image_payload = {
        "prompt": "a green grassy hill",
        "workspace_id": e2e_test_workspace,
        "metadata_generation_model": "gemini-3.5-flash",
        "generation_model": "gemini-3.1-flash-image-preview",
        "aspect_ratio": "1:1",
    }
    img_resp = e2e_client.post(
        "/api/images/generate-images", json=image_payload
    )
    assert img_resp.status_code == 200
    image_id = img_resp.json()["id"]

    # Wait for completion
    db_image = await wait_for_completion(image_id)
    assert db_image.status == JobStatusEnum.COMPLETED

    # 2. Call multimodal generation referencing the generated image
    payload = {
        "workspace_id": e2e_test_workspace,
        "prompt": "What is in this generated image?",
        "media_item_ids": [image_id],
        "model": "gemini-3.5-flash",
    }
    resp = e2e_client.post("/api/gemini/multimodal-generation", json=payload)
    assert resp.status_code == 200
    assert resp.json()["text"] == "Mock Multimodal Generated Content Text"


@pytest.mark.anyio
async def test_integration_workspace_boundaries(
    e2e_client, mock_user, e2e_test_workspace
):
    """Tier 3: Workspace boundaries: verify asset uploaded to Workspace A cannot be read in Workspace B by unauthorized users."""
    from main import app
    from src.auth.auth_guard import get_current_user
    from src.users.user_model import User, UserModel, UserRoleEnum

    # 1. Create a second regular user (mock_user_b)
    mock_user_b = UserModel(
        id=4,
        email="user_b@example.com",
        roles=[UserRoleEnum.USER],
        name="User B",
        picture="http://example.com/user_b.jpg",
    )
    async with async_session_local() as session:
        res = await session.execute(
            select(User).where(User.id == mock_user_b.id)
        )
        u = res.scalar_one_or_none()
        if not u:
            new_user = User(
                id=mock_user_b.id,
                email=mock_user_b.email,
                roles=["user"],
                name=mock_user_b.name,
                picture=mock_user_b.picture,
            )
            session.add(new_user)
            await session.commit()

    try:
        # 2. Workspace A (e2e_test_workspace) is owned/associated with regular user.
        # Upload asset to Workspace A acting as mock_user.
        app.dependency_overrides[get_current_user] = lambda: mock_user

        png_data = get_valid_png_bytes()
        files = {"file": ("workspace_a_logo.png", png_data, "image/png")}
        data = {
            "workspaceId": e2e_test_workspace,
            "metadata_generation_model": "gemini-3.5-flash",
        }
        upload_resp = e2e_client.post(
            "/api/source_assets/upload", files=files, data=data
        )
        assert upload_resp.status_code == 200
        asset_id = upload_resp.json()["id"]

        # 3. Act as mock_user_b: Create Workspace B
        app.dependency_overrides[get_current_user] = lambda: mock_user_b
        workspace_b_resp = e2e_client.post(
            "/api/workspaces", json={"name": "E2E User B Workspace B"}
        )
        assert workspace_b_resp.status_code == 201
        workspace_b_id = workspace_b_resp.json()["id"]

        try:
            # 4. User B attempts to fetch the Workspace A asset.
            # Should return 404 since they are not the owner, not admin, and it's not a public/system asset.
            get_resp = e2e_client.get(f"/api/source_assets/{asset_id}")
            assert get_resp.status_code == 404

            # 5. User B searches/lists assets. The search result must NOT include Workspace A asset.
            search_payload = {
                "limit": 10,
                "offset": 0,
            }
            search_resp = e2e_client.post(
                "/api/source_assets/search", json=search_payload
            )
            assert search_resp.status_code == 200
            search_results = search_resp.json().get("data") or []
            asset_ids_found = [item["id"] for item in search_results]
            assert asset_id not in asset_ids_found

        finally:
            # Cleanup Workspace B
            async with async_session_local() as session:
                await session.execute(
                    delete(WorkspaceMemberAssociation).where(
                        WorkspaceMemberAssociation.workspace_id
                        == workspace_b_id
                    )
                )
                await session.execute(
                    delete(Workspace).where(Workspace.id == workspace_b_id)
                )
                await session.commit()
    finally:
        # Cleanup mock_user_b from DB
        async with async_session_local() as session:
            await session.execute(delete(User).where(User.id == mock_user_b.id))
            await session.commit()
        # Restore mock_user override
        app.dependency_overrides[get_current_user] = lambda: mock_user


@pytest.mark.anyio
async def test_integration_concurrent_generations(
    e2e_client, e2e_test_workspace
):
    """Tier 3: Concurrent background generation jobs: submit multiple concurrent generation tasks and verify they complete safely."""
    image_payload_1 = {
        "prompt": "red apple",
        "workspace_id": e2e_test_workspace,
        "metadata_generation_model": "gemini-3.5-flash",
        "generation_model": "gemini-3.1-flash-image-preview",
        "aspect_ratio": "1:1",
    }
    image_payload_2 = {
        "prompt": "yellow banana",
        "workspace_id": e2e_test_workspace,
        "metadata_generation_model": "gemini-3.5-flash",
        "generation_model": "gemini-3.1-flash-image-preview",
        "aspect_ratio": "1:1",
    }
    image_payload_3 = {
        "prompt": "purple grape",
        "workspace_id": e2e_test_workspace,
        "metadata_generation_model": "gemini-3.5-flash",
        "generation_model": "gemini-3.1-flash-image-preview",
        "aspect_ratio": "1:1",
    }

    # Submit 3 jobs in sequence (they return immediately and queue background tasks)
    resp1 = e2e_client.post("/api/images/generate-images", json=image_payload_1)
    resp2 = e2e_client.post("/api/images/generate-images", json=image_payload_2)
    resp3 = e2e_client.post("/api/images/generate-images", json=image_payload_3)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 200

    id1 = resp1.json()["id"]
    id2 = resp2.json()["id"]
    id3 = resp3.json()["id"]

    # Poll and wait for completion concurrently
    results = await asyncio.gather(
        wait_for_completion(id1),
        wait_for_completion(id2),
        wait_for_completion(id3),
    )

    for item in results:
        assert item.status == JobStatusEnum.COMPLETED


@pytest.mark.anyio
async def test_integration_full_creative_workflow(
    e2e_client, e2e_test_workspace
):
    """Tier 4: Full creative workflow: upload logo -> generate image -> generate video using image -> multimodal prompt -> lineage checks -> cleanup."""
    # 1. Upload logo source asset
    png_data = get_valid_png_bytes()
    files = {"file": ("company_logo.png", png_data, "image/png")}
    data = {
        "workspaceId": e2e_test_workspace,
        "metadata_generation_model": "gemini-3.5-flash",
    }
    upload_resp = e2e_client.post(
        "/api/source_assets/upload", files=files, data=data
    )
    assert upload_resp.status_code == 200
    logo_asset_id = upload_resp.json()["id"]

    # 2. Generate background image
    image_payload = {
        "prompt": "corporate office background",
        "workspace_id": e2e_test_workspace,
        "metadata_generation_model": "gemini-3.5-flash",
        "generation_model": "gemini-3.1-flash-image-preview",
        "aspect_ratio": "1:1",
    }
    img_resp = e2e_client.post(
        "/api/images/generate-images", json=image_payload
    )
    assert img_resp.status_code == 200
    image_id = img_resp.json()["id"]
    db_image = await wait_for_completion(image_id)
    assert db_image.status == JobStatusEnum.COMPLETED

    # 3. Generate video using the generated image as a starting frame
    video_payload = {
        "prompt": "camera pan across corporate office background",
        "workspace_id": e2e_test_workspace,
        "metadata_generation_model": "gemini-3.5-flash",
        "generation_model": "veo-3.1-generate-001",
        "aspect_ratio": "16:9",
        "duration_seconds": 8,
        "start_image_asset_id": {"id": image_id, "type": "media_item"},
    }
    video_resp = e2e_client.post(
        "/api/videos/generate-videos", json=video_payload
    )
    assert video_resp.status_code == 200
    video_id = video_resp.json()["id"]
    db_video = await wait_for_completion(video_id)
    assert db_video.status == JobStatusEnum.COMPLETED

    # Check database lineage
    async with async_session_local() as session:
        query = select(MediaItem).where(MediaItem.id == video_id)
        res = await session.execute(query)
        video_record = res.scalar_one()

        # Verify that start_image_asset_id mapped correctly to source_media_items in the video record
        assert video_record.source_media_items is not None
        assert len(video_record.source_media_items) == 1
        link = video_record.source_media_items[0]
        # support both camelCase and snake_case depending on JSON serialization
        assert (
            link.get("mediaItemId") == image_id
            or link.get("media_item_id") == image_id
        )
        assert link.get("role") == AssetRoleEnum.START_FRAME.value

    # 4. Multimodal Generation combining logo, image, and video
    multimodal_payload = {
        "workspace_id": e2e_test_workspace,
        "prompt": "Create an ad copy using this logo, image, and video",
        "source_asset_ids": [logo_asset_id],
        "media_item_ids": [image_id, video_id],
        "model": "gemini-3.5-flash",
    }
    mm_resp = e2e_client.post(
        "/api/gemini/multimodal-generation", json=multimodal_payload
    )
    assert mm_resp.status_code == 200
    assert mm_resp.json()["text"] == "Mock Multimodal Generated Content Text"
