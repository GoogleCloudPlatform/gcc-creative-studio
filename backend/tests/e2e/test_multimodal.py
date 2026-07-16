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
"""E2E tests for Multimodal Generation (R1)."""

import pytest
from unittest.mock import MagicMock

from src.common.schema.media_item_model import MediaItem, JobStatusEnum
from src.source_assets.schema.source_asset_model import SourceAsset


@pytest.mark.anyio
async def test_multimodal_generation_prompt_only(
    e2e_client, e2e_test_workspace
):
    """Tier 1: Successful text generation with prompt only."""
    payload = {
        "workspace_id": e2e_test_workspace,
        "prompt": "Write a slogan for a new coffee brand",
        "model": "gemini-3.5-flash",
    }
    resp = e2e_client.post("/api/gemini/multimodal-generation", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "text" in data
    assert data["text"] == "Mock Multimodal Generated Content Text"


@pytest.mark.anyio
async def test_multimodal_generation_creator_role(e2e_creator_client):
    """Successful text generation using CREATOR role."""
    resp_ws = e2e_creator_client.post(
        "/api/workspaces", json={"name": "Creator Workspace"}
    )
    assert resp_ws.status_code == 201
    workspace_id = resp_ws.json()["id"]

    try:
        payload = {
            "workspace_id": workspace_id,
            "prompt": "Write a slogan for a new coffee brand",
            "model": "gemini-3.5-flash",
        }
        resp = e2e_creator_client.post(
            "/api/gemini/multimodal-generation", json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "Mock Multimodal Generated Content Text"
    finally:
        # Cleanup workspace
        from src.database import async_session_local
        from src.workspaces.schema.workspace_model import (
            Workspace,
            WorkspaceMemberAssociation,
        )
        from sqlalchemy import delete

        async with async_session_local() as session:
            await session.execute(
                delete(WorkspaceMemberAssociation).where(
                    WorkspaceMemberAssociation.workspace_id == workspace_id
                )
            )
            await session.execute(
                delete(Workspace).where(Workspace.id == workspace_id)
            )
            await session.commit()


@pytest.mark.anyio
async def test_multimodal_generation_custom_model(
    e2e_client, e2e_test_workspace
):
    """Tier 1: Text generation with a custom model configuration."""
    payload = {
        "workspace_id": e2e_test_workspace,
        "prompt": "Write a short poem",
        "model": "gemini-2.5-pro",
    }
    resp = e2e_client.post("/api/gemini/multimodal-generation", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "Mock Multimodal Generated Content Text"


@pytest.mark.anyio
async def test_multimodal_generation_with_single_source_asset(
    e2e_client, e2e_test_workspace
):
    """Tier 1: Text generation with a single source asset reference."""
    # 1. Create a dummy source asset in the DB for this workspace
    from src.database import async_session_local

    async with async_session_local() as session:
        asset = SourceAsset(
            workspace_id=e2e_test_workspace,
            user_id=1,
            gcs_uri="gs://mock-bucket/assets/coffee_logo.png",
            mime_type="image/png",
            original_filename="coffee_logo.png",
            file_hash="mock-hash",
            titles=["Coffee Logo"],
            descriptions=["A logo for coffee brand"],
        )
        session.add(asset)
        await session.commit()
        await session.refresh(asset)
        asset_id = asset.id

    # 2. Call multimodal generation referencing the asset
    payload = {
        "workspace_id": e2e_test_workspace,
        "prompt": "Describe this logo",
        "source_asset_ids": [asset_id],
        "model": "gemini-3.5-flash",
    }
    resp = e2e_client.post("/api/gemini/multimodal-generation", json=payload)
    assert resp.status_code == 200
    assert resp.json()["text"] == "Mock Multimodal Generated Content Text"


@pytest.mark.anyio
async def test_multimodal_generation_with_single_media_item(
    e2e_client, e2e_test_workspace
):
    """Tier 1: Text generation with a single media item reference."""
    # 1. Create a dummy media item in the DB for this workspace
    from src.database import async_session_local

    async with async_session_local() as session:
        media_item = MediaItem(
            workspace_id=e2e_test_workspace,
            user_id=1,
            user_email="regular@user.com",
            model="imagen-3.0-generate-002",
            aspect_ratio="1:1",
            gcs_uris=["gs://mock-bucket/generated_coffee.png"],
            mime_type="image/png",
            status=JobStatusEnum.COMPLETED,
            titles=["Generated Coffee Cup"],
            descriptions=["A cup of coffee"],
        )
        session.add(media_item)
        await session.commit()
        await session.refresh(media_item)
        media_id = media_item.id

    # 2. Call multimodal generation referencing the media item
    payload = {
        "workspace_id": e2e_test_workspace,
        "prompt": "Analyze this generated image",
        "media_item_ids": [media_id],
        "model": "gemini-3.5-flash",
    }
    resp = e2e_client.post("/api/gemini/multimodal-generation", json=payload)
    assert resp.status_code == 200
    assert resp.json()["text"] == "Mock Multimodal Generated Content Text"


@pytest.mark.anyio
async def test_multimodal_generation_with_mixed_assets(
    e2e_client, e2e_test_workspace
):
    """Tier 1: Text generation referencing both source assets and media items."""
    from src.database import async_session_local

    async with async_session_local() as session:
        # Create source asset
        asset = SourceAsset(
            workspace_id=e2e_test_workspace,
            user_id=1,
            gcs_uri="gs://mock-bucket/assets/brand_colors.png",
            mime_type="image/png",
            original_filename="colors.png",
            file_hash="mock-hash",
            titles=["Brand Colors"],
            descriptions=["Colors of the brand"],
        )
        session.add(asset)
        # Create media item
        media_item = MediaItem(
            workspace_id=e2e_test_workspace,
            user_id=1,
            user_email="regular@user.com",
            model="imagen-3.0-generate-002",
            aspect_ratio="1:1",
            gcs_uris=["gs://mock-bucket/generated_cup.png"],
            mime_type="image/png",
            status=JobStatusEnum.COMPLETED,
            titles=["Generated Cup"],
            descriptions=["A cup"],
        )
        session.add(media_item)
        await session.commit()
        await session.refresh(asset)
        await session.refresh(media_item)
        asset_id = asset.id
        media_id = media_item.id

    payload = {
        "workspace_id": e2e_test_workspace,
        "prompt": "Does this cup match the brand colors?",
        "source_asset_ids": [asset_id],
        "media_item_ids": [media_id],
        "model": "gemini-3.5-flash",
    }
    resp = e2e_client.post("/api/gemini/multimodal-generation", json=payload)
    assert resp.status_code == 200
    assert resp.json()["text"] == "Mock Multimodal Generated Content Text"


@pytest.mark.anyio
async def test_multimodal_generation_unauthenticated(
    e2e_unauthenticated_client,
):
    """Tier 2: Request without authentication fails with 401."""
    payload = {
        "workspace_id": 99999,
        "prompt": "Should fail",
        "model": "gemini-3.5-flash",
    }
    resp = e2e_unauthenticated_client.post(
        "/api/gemini/multimodal-generation", json=payload
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_multimodal_generation_nonexistent_assets(
    e2e_client, e2e_test_workspace
):
    """Tier 2: Request referencing nonexistent asset IDs succeeds by skipping them."""
    payload = {
        "workspace_id": e2e_test_workspace,
        "prompt": "Describe this nonexistent logo",
        "source_asset_ids": [999999],
        "media_item_ids": [888888],
        "model": "gemini-3.5-flash",
    }
    resp = e2e_client.post("/api/gemini/multimodal-generation", json=payload)
    assert resp.status_code == 200
    assert resp.json()["text"] == "Mock Multimodal Generated Content Text"


@pytest.mark.anyio
async def test_multimodal_generation_exception_handling(
    e2e_client, e2e_test_workspace
):
    """Tier 2: Gemini exceptions are handled gracefully and return a 500 error."""
    # The MockGenAIClient is configured to raise an Exception if prompt contains "trigger_exception"
    payload = {
        "workspace_id": e2e_test_workspace,
        "prompt": "trigger_exception",
        "model": "gemini-3.5-flash",
    }
    # Modify our MockGenAIClient's async_gen mock logic inside this test run
    from src.common.schema.genai_model_setup import GenAIModelSetup

    client_mock = GenAIModelSetup.get_client()

    async def async_gen_exception(model, contents, config=None, **kwargs):
        raise Exception("Google API is down")

    client_mock.aio.models.generate_content = async_gen_exception

    try:
        resp = e2e_client.post(
            "/api/gemini/multimodal-generation", json=payload
        )
        assert resp.status_code == 500
        assert "Google API is down" in resp.json()["detail"]
    finally:
        # Restore the original mock async_gen
        async def async_gen(model, contents, config=None, **kwargs):
            mock_res = MagicMock()
            mock_res.text = "Mock Multimodal Generated Content Text"
            return mock_res

        client_mock.aio.models.generate_content = async_gen


@pytest.mark.anyio
async def test_multimodal_generation_workspace_not_found(e2e_client):
    """Test workspace authorization failure when workspace does not exist."""
    payload = {
        "workspace_id": 999999,
        "prompt": "Workspace not found test",
        "model": "gemini-3.5-flash",
    }
    resp = e2e_client.post("/api/gemini/multimodal-generation", json=payload)
    assert resp.status_code == 404
    assert "Workspace with ID '999999' not found." in resp.json()["detail"]


@pytest.mark.anyio
async def test_multimodal_generation_workspace_mismatch_media_item(
    e2e_client, e2e_test_workspace
):
    """Test boundary check when a media item belongs to a different workspace."""
    # 1. Create a second workspace in DB
    resp_ws = e2e_client.post(
        "/api/workspaces", json={"name": "Second Temporary Test Workspace"}
    )
    assert resp_ws.status_code == 201
    second_ws_id = resp_ws.json()["id"]

    try:
        # 2. Create a media item in the second workspace
        from src.database import async_session_local

        async with async_session_local() as session:
            media_item = MediaItem(
                workspace_id=second_ws_id,
                user_id=1,
                user_email="regular@user.com",
                model="imagen-3.0-generate-002",
                aspect_ratio="1:1",
                gcs_uris=["gs://mock-bucket/generated_coffee.png"],
                mime_type="image/png",
                status=JobStatusEnum.COMPLETED,
                titles=["Generated Coffee Cup"],
                descriptions=["A cup of coffee"],
            )
            session.add(media_item)
            await session.commit()
            await session.refresh(media_item)
            media_id = media_item.id

        # 3. Call multimodal generation for e2e_test_workspace using the media item of the second workspace
        payload = {
            "workspace_id": e2e_test_workspace,
            "prompt": "Analyze this image",
            "media_item_ids": [media_id],
            "model": "gemini-3.5-flash",
        }
        resp = e2e_client.post(
            "/api/gemini/multimodal-generation", json=payload
        )
        assert resp.status_code == 403
        assert (
            f"Media item {media_id} does not belong to workspace"
            in resp.json()["detail"]
        )
    finally:
        # Cleanup second workspace and its media items
        from src.database import async_session_local
        from src.workspaces.schema.workspace_model import (
            Workspace,
            WorkspaceMemberAssociation,
        )
        from sqlalchemy import delete

        async with async_session_local() as session:
            await session.execute(
                delete(MediaItem).where(MediaItem.workspace_id == second_ws_id)
            )
            await session.execute(
                delete(WorkspaceMemberAssociation).where(
                    WorkspaceMemberAssociation.workspace_id == second_ws_id
                )
            )
            await session.execute(
                delete(Workspace).where(Workspace.id == second_ws_id)
            )
            await session.commit()


@pytest.mark.anyio
async def test_multimodal_generation_workspace_mismatch_source_asset(
    e2e_client, e2e_test_workspace
):
    """Test boundary check when a source asset belongs to a different workspace."""
    # 1. Create a second workspace in DB
    resp_ws = e2e_client.post(
        "/api/workspaces", json={"name": "Second Temporary Test Workspace"}
    )
    assert resp_ws.status_code == 201
    second_ws_id = resp_ws.json()["id"]

    try:
        # 2. Create a source asset in the second workspace
        from src.database import async_session_local

        async with async_session_local() as session:
            asset = SourceAsset(
                workspace_id=second_ws_id,
                user_id=1,
                gcs_uri="gs://mock-bucket/assets/coffee_logo.png",
                mime_type="image/png",
                original_filename="coffee_logo.png",
                file_hash="mock-hash",
                titles=["Coffee Logo"],
                descriptions=["A logo for coffee brand"],
            )
            session.add(asset)
            await session.commit()
            await session.refresh(asset)
            asset_id = asset.id

        # 3. Call multimodal generation for e2e_test_workspace using the asset of the second workspace
        payload = {
            "workspace_id": e2e_test_workspace,
            "prompt": "Analyze this logo",
            "source_asset_ids": [asset_id],
            "model": "gemini-3.5-flash",
        }
        resp = e2e_client.post(
            "/api/gemini/multimodal-generation", json=payload
        )
        assert resp.status_code == 403
        assert (
            f"Asset {asset_id} does not belong to workspace"
            in resp.json()["detail"]
        )
    finally:
        # Cleanup second workspace and its source assets
        from src.database import async_session_local
        from src.workspaces.schema.workspace_model import (
            Workspace,
            WorkspaceMemberAssociation,
        )
        from sqlalchemy import delete

        async with async_session_local() as session:
            await session.execute(
                delete(SourceAsset).where(
                    SourceAsset.workspace_id == second_ws_id
                )
            )
            await session.execute(
                delete(WorkspaceMemberAssociation).where(
                    WorkspaceMemberAssociation.workspace_id == second_ws_id
                )
            )
            await session.execute(
                delete(Workspace).where(Workspace.id == second_ws_id)
            )
            await session.commit()
