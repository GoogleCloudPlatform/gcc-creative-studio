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

from contextlib import asynccontextmanager
import pytest
from unittest.mock import MagicMock

from sqlalchemy import delete, select

from src.common.schema.media_item_model import MediaItem, JobStatusEnum
from src.database import async_session_local
from src.source_assets.schema.source_asset_model import SourceAsset
from src.users.user_model import User, UserRoleEnum
from src.workspaces.schema.workspace_model import (
    Workspace,
    WorkspaceMemberAssociation,
    WorkspaceScopeEnum,
)


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
        "model": "gemini-4-argon",
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


async def _cleanup_workspace(ws_id: int) -> None:
    async with async_session_local() as session:
        await session.execute(
            delete(MediaItem).where(MediaItem.workspace_id == ws_id)
        )
        await session.execute(
            delete(SourceAsset).where(SourceAsset.workspace_id == ws_id)
        )
        await session.execute(
            delete(WorkspaceMemberAssociation).where(
                WorkspaceMemberAssociation.workspace_id == ws_id
            )
        )
        await session.execute(delete(Workspace).where(Workspace.id == ws_id))
        await session.commit()


@asynccontextmanager
async def _foreign_private_workspace(name: str):
    foreign_uid = 904
    async with async_session_local() as session:
        res = await session.execute(select(User).where(User.id == foreign_uid))
        if res.scalar_one_or_none() is None:
            session.add(
                User(
                    id=foreign_uid,
                    email="foreign_mm@example.com",
                    roles=[UserRoleEnum.USER.value],
                    name="Foreign User",
                    picture="http://example.com/foreign.jpg",
                )
            )
            await session.flush()
        ws = Workspace(
            name=name,
            owner_id=foreign_uid,
            scope=WorkspaceScopeEnum.PRIVATE.value,
        )
        session.add(ws)
        await session.commit()
        await session.refresh(ws)
        ws_id = ws.id
    try:
        yield ws_id, foreign_uid
    finally:
        await _cleanup_workspace(ws_id)
        async with async_session_local() as session:
            await session.execute(delete(User).where(User.id == foreign_uid))
            await session.commit()


@pytest.mark.anyio
async def test_multimodal_generation_workspace_mismatch_media_item(
    e2e_client, e2e_test_workspace
):
    """Readable cross-workspace references pass; foreign private references return 403."""
    resp_ws = e2e_client.post(
        "/api/workspaces", json={"name": "Second Temporary Test Workspace"}
    )
    assert resp_ws.status_code == 201
    second_ws_id = resp_ws.json()["id"]

    try:
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
            readable_media_id = media_item.id

        ok_resp = e2e_client.post(
            "/api/gemini/multimodal-generation",
            json={
                "workspace_id": e2e_test_workspace,
                "prompt": "Analyze this readable cross-workspace image",
                "media_item_ids": [readable_media_id],
                "model": "gemini-3.5-flash",
            },
        )
        assert ok_resp.status_code == 200
        assert (
            ok_resp.json()["text"] == "Mock Multimodal Generated Content Text"
        )

        async with _foreign_private_workspace("Foreign Media Workspace") as (
            foreign_ws_id,
            foreign_uid,
        ):
            async with async_session_local() as session:
                foreign_item = MediaItem(
                    workspace_id=foreign_ws_id,
                    user_id=foreign_uid,
                    user_email="foreign_mm@example.com",
                    model="imagen-3.0-generate-002",
                    aspect_ratio="1:1",
                    gcs_uris=["gs://mock-bucket/foreign_coffee.png"],
                    mime_type="image/png",
                    status=JobStatusEnum.COMPLETED,
                    titles=["Foreign Coffee Cup"],
                    descriptions=["Foreign private image"],
                )
                session.add(foreign_item)
                await session.commit()
                await session.refresh(foreign_item)
                foreign_media_id = foreign_item.id

            forb_resp = e2e_client.post(
                "/api/gemini/multimodal-generation",
                json={
                    "workspace_id": e2e_test_workspace,
                    "prompt": "Analyze unauthorized image",
                    "media_item_ids": [foreign_media_id],
                    "model": "gemini-3.5-flash",
                },
            )
            assert forb_resp.status_code == 403
            assert "permission" in forb_resp.json()["detail"].lower()
    finally:
        await _cleanup_workspace(second_ws_id)


@pytest.mark.anyio
async def test_multimodal_generation_workspace_mismatch_source_asset(
    e2e_client, e2e_test_workspace
):
    """Readable cross-workspace assets pass; foreign private assets return 403."""
    resp_ws = e2e_client.post(
        "/api/workspaces", json={"name": "Second Temporary Test Workspace"}
    )
    assert resp_ws.status_code == 201
    second_ws_id = resp_ws.json()["id"]

    try:
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
            readable_asset_id = asset.id

        ok_resp = e2e_client.post(
            "/api/gemini/multimodal-generation",
            json={
                "workspace_id": e2e_test_workspace,
                "prompt": "Analyze this readable cross-workspace logo",
                "source_asset_ids": [readable_asset_id],
                "model": "gemini-3.5-flash",
            },
        )
        assert ok_resp.status_code == 200
        assert (
            ok_resp.json()["text"] == "Mock Multimodal Generated Content Text"
        )

        async with _foreign_private_workspace("Foreign Asset Workspace") as (
            foreign_ws_id,
            foreign_uid,
        ):
            async with async_session_local() as session:
                foreign_asset = SourceAsset(
                    workspace_id=foreign_ws_id,
                    user_id=foreign_uid,
                    gcs_uri="gs://mock-bucket/assets/foreign_logo.png",
                    mime_type="image/png",
                    original_filename="foreign_logo.png",
                    file_hash="foreign-hash",
                    titles=["Foreign Logo"],
                    descriptions=["Foreign private logo"],
                )
                session.add(foreign_asset)
                await session.commit()
                await session.refresh(foreign_asset)
                foreign_asset_id = foreign_asset.id

            forb_resp = e2e_client.post(
                "/api/gemini/multimodal-generation",
                json={
                    "workspace_id": e2e_test_workspace,
                    "prompt": "Analyze unauthorized logo",
                    "source_asset_ids": [foreign_asset_id],
                    "model": "gemini-3.5-flash",
                },
            )
            assert forb_resp.status_code == 403
            assert "permission" in forb_resp.json()["detail"].lower()
    finally:
        await _cleanup_workspace(second_ws_id)
