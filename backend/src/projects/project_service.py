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

import asyncio
import logging
from fastapi import Depends, HTTPException, status
from src.agents.agent_session_repository import AgentSessionRepository
from src.projects.project_auth_guard import ProjectAuth
from src.projects.project_repository import (
    ProjectRepository,
    StoryboardRepository,
)
from src.images.repository.media_item_repository import MediaRepository
from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.projects.dto.project_dto import (
    ProjectCreate,
    ProjectResponse,
    StoryboardResponse,
    StoryboardCreateResponse,
    StoryboardCreate,
    StoryboardUpdate,
    SceneDTO,
)
from src.users.user_model import UserModel
from src.workspaces.workspace_auth_guard import WorkspaceAuth

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_DELETE_DETAIL = "The default project cannot be deleted."


class ProjectService:
    """Service for the Project aggregate: projects and their storyboards."""

    def __init__(
        self,
        storyboard_repo: StoryboardRepository = Depends(),
        media_repo: MediaRepository = Depends(),
        iam_signer_credentials: IamSignerCredentials = Depends(),
        project_repo: ProjectRepository = Depends(),
        project_auth: ProjectAuth = Depends(),
        workspace_auth: WorkspaceAuth = Depends(),
        agent_session_repo: AgentSessionRepository = Depends(),
    ):
        self.storyboard_repo = storyboard_repo
        self.media_repo = media_repo
        self.iam_signer_credentials = iam_signer_credentials
        self.project_repo = project_repo
        self.project_auth = project_auth
        self.workspace_auth = workspace_auth
        self.agent_session_repo = agent_session_repo

    # --- Projects -------------------------------------------------------

    async def list_projects(
        self, user: UserModel, workspace_id: int
    ) -> list[ProjectResponse]:
        """The caller's own projects in a workspace (owner-only feature)."""
        await self.workspace_auth.authorize(
            workspace_id=workspace_id, user=user
        )
        return await self.project_repo.list_for_owner(workspace_id, user.id)

    async def ensure_default_project(
        self, user: UserModel, workspace_id: int
    ) -> ProjectResponse:
        """The caller's default project in a workspace, created on demand."""
        await self.workspace_auth.authorize(
            workspace_id=workspace_id, user=user
        )
        project = await self.project_repo.ensure_default(workspace_id, user.id)
        return await self.project_repo.get_summary(project.id) or project

    async def create_project(
        self, user: UserModel, project_create: ProjectCreate
    ) -> ProjectResponse:
        await self.workspace_auth.authorize(
            workspace_id=project_create.workspace_id, user=user
        )
        return await self.project_repo.create_project(
            project_create.workspace_id, user.id, project_create.name
        )

    async def get_project(
        self, user: UserModel, project_id: int
    ) -> ProjectResponse:
        await self.project_auth.authorize(project_id, user)
        project = await self.project_repo.get_summary(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project with ID '{project_id}' not found.",
            )
        return project

    async def rename_project(
        self, user: UserModel, project_id: int, name: str
    ) -> ProjectResponse:
        await self.project_auth.authorize(project_id, user)
        await self.project_repo.update(project_id, {"name": name})
        return await self.get_project(user, project_id)

    async def prepare_project_delete(
        self, user: UserModel, project_id: int
    ) -> dict[str, str]:
        """Authorizes deleting a project and returns its chats as
        ``{session_id: app_name}``.

        The first step of a delete: it runs before the agent sessions are
        removed, so a refused delete leaves everything intact.
        """
        await self._authorize_project_delete(user, project_id)
        return await self.agent_session_repo.app_names_for_project(project_id)

    async def delete_project(self, user: UserModel, project_id: int) -> None:
        """Deletes the project and, through ON DELETE CASCADE, its chats'
        registry rows, storyboards (and scenes) and timelines (and clips).

        Authorizes again, so the destructive step is safe on its own. The
        agent sessions live outside the database: the caller removes them
        first (see ``prepare_project_delete``).
        """
        await self._authorize_project_delete(user, project_id)
        await self.project_repo.delete(project_id)

    async def _authorize_project_delete(
        self, user: UserModel, project_id: int
    ) -> ProjectResponse:
        """Owner-only (``ProjectAuth``), and never the default project (409).

        Deleting the default project only threw its content away:
        ``ensure_default`` re-creates an empty one on the next agent save,
        chat listing or Workbench visit.
        """
        project = await self.project_auth.authorize(project_id, user)
        if project.is_default:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=DEFAULT_PROJECT_DELETE_DETAIL,
            )
        return project

    async def resolve_project_from_child(
        self,
        user: UserModel,
        session_id: str | None = None,
        storyboard_id: int | None = None,
        timeline_id: int | None = None,
    ) -> ProjectResponse:
        """The project that owns a deep-linked chat, storyboard or timeline.

        Exactly one id must be given. Each id type is looked up in its own
        table, so ids that collide across tables cannot match the wrong
        project.
        """
        provided = [
            value
            for value in (session_id, storyboard_id, timeline_id)
            if value not in (None, "")
        ]
        if len(provided) != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Provide exactly one of session_id, storyboard_id or "
                    "timeline_id."
                ),
            )
        if session_id:
            row = await self.agent_session_repo.get(session_id)
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="This chat is not registered in any project.",
                )
            if row.user_id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to access this chat.",
                )
            project_id = row.project_id
        elif storyboard_id is not None:
            owner = await self.storyboard_repo.get_owner_and_project(
                storyboard_id
            )
            if owner is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Storyboard not found",
                )
            if owner[0] != user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to access this storyboard",
                )
            project_id = owner[1]
        else:
            exists, project_id = await self.project_repo.get_timeline_project(
                timeline_id  # type: ignore[arg-type]
            )
            if not exists or project_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Timeline not found",
                )
        return await self.get_project(user, project_id)

    async def authorize_storyboard(
        self, user: UserModel, storyboard_id: int
    ) -> ProjectResponse:
        """The project of a storyboard ``user`` owns (404/403 otherwise)."""
        owner = await self.storyboard_repo.get_owner_and_project(storyboard_id)
        if owner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Storyboard not found",
            )
        if owner[0] != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to use this storyboard",
            )
        return await self.project_auth.authorize(owner[1], user)

    async def resolve_project_for_write(
        self,
        user: UserModel,
        workspace_id: int | None,
        project_id: int | None = None,
        storyboard_id: int | None = None,
        session_id: str | None = None,
    ) -> ProjectResponse:
        """Picks the project a new storyboard, timeline or chat belongs to.

        Priority: the storyboard's project, then an explicit ``project_id``,
        then the chat's registered project (Izumi only ever sends
        ``session_id``), then the user's default project. Ownership and
        workspace access are enforced on every path. ``workspace_id`` may be
        None only when a storyboard or project already determines the
        workspace.

        An unregistered ``session_id`` is never adopted here: it comes from
        the client and proves nothing about who owns the chat, so adopting
        it let a caller claim (then delete) another user's chat. The
        user-scoped ``list_sessions`` adopts it into the same default project.
        """
        if storyboard_id is not None:
            return await self.authorize_storyboard(user, storyboard_id)

        if project_id is not None:
            project = await self.project_auth.authorize(project_id, user)
            if (
                workspace_id is not None
                and project.workspace_id != workspace_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The project belongs to another workspace.",
                )
            return project

        if workspace_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A numeric workspace_id is required.",
            )

        if session_id:
            row = await self.agent_session_repo.get(session_id)
            if row is not None:
                if row.user_id != user.id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not authorized to use this chat",
                    )
                if row.workspace_id == workspace_id:
                    return await self.project_auth.authorize(
                        row.project_id, user
                    )
                logger.warning(
                    "[Projects] session_id=%s is registered in workspace %s "
                    "but was used in workspace %s; using that workspace's "
                    "default project",
                    session_id,
                    row.workspace_id,
                    workspace_id,
                )

        await self.workspace_auth.authorize(
            workspace_id=workspace_id, user=user
        )
        return await self.project_repo.ensure_default(workspace_id, user.id)

    # --- Storyboards ----------------------------------------------------

    async def _enrich_storyboard(self, storyboard: StoryboardResponse):
        """Enriches a storyboard with presigned URLs."""
        for scene in storyboard.scenes:
            if scene.first_frame_media_item_id:
                media_item = await self.media_repo.get_by_id(
                    scene.first_frame_media_item_id
                )
                if media_item and media_item.gcs_uris:
                    gcs_uri = media_item.gcs_uris[0]
                    presigned_url = await asyncio.to_thread(
                        self.iam_signer_credentials.generate_presigned_url,
                        gcs_uri,
                    )
                    scene.first_frame_generated_url = presigned_url

    async def create_storyboard(
        self,
        storyboard_create: StoryboardCreate,
        user: UserModel,
        reuse_session_record: bool = False,
    ) -> StoryboardCreateResponse:
        """Creates a storyboard record in its project.

        With ``reuse_session_record`` (the agent's create path) a session that
        already owns a storyboard gets that record back, with the scalar
        fields refreshed, instead of a second one: Izumi re-creates its
        storyboard on every pipeline restart and would otherwise leave the
        Workbench pointing at a stale record.

        A new record's project comes from ``resolve_project_for_write``.
        Izumi sends no ``project_id``, so the chat's registered project is
        used.
        """
        data = storyboard_create.model_dump()
        data["user_id"] = user.id
        session_id = storyboard_create.session_id
        if reuse_session_record and session_id:
            existing = await self.storyboard_repo.find_latest_by_session(
                storyboard_create.workspace_id, session_id, user.id
            )
            if existing:
                scalar_updates = {
                    key: data[key]
                    for key in (
                        "template_name",
                        "bg_music_description",
                        "bg_music_asset_id",
                    )
                    if data.get(key) is not None
                }
                if scalar_updates:
                    await self.storyboard_repo.update(
                        existing.id, scalar_updates
                    )
                    existing = existing.model_copy(update=scalar_updates)
                return existing
        project = await self.resolve_project_for_write(
            user,
            storyboard_create.workspace_id,
            project_id=storyboard_create.project_id,
            session_id=session_id,
        )
        data["project_id"] = project.id
        return await self.storyboard_repo.create(data)

    async def get_storyboard(
        self, storyboard_id: int
    ) -> StoryboardResponse | None:
        storyboard = await self.storyboard_repo.get_by_id_with_details(
            storyboard_id
        )
        if storyboard:
            await self._enrich_storyboard(storyboard)
        return storyboard

    async def list_storyboards(
        self,
        workspace_id: int,
        session_id: str | None = None,
        user_id: int | None = None,
    ) -> list[StoryboardResponse]:
        storyboards = await self.storyboard_repo.find_by_workspace(
            workspace_id, session_id, user_id
        )
        for sb in storyboards:
            await self._enrich_storyboard(sb)
        return storyboards

    async def list_storyboards_for_user(
        self,
        user: UserModel,
        workspace_id: int,
        session_id: str | None = None,
    ) -> list[StoryboardResponse]:
        """``GET /api/storyboards``: the caller's own storyboards only.

        The workspace is authorized first. Before this, any signed-in user
        could list another workspace's storyboards, presigned URLs included.
        """
        await self.workspace_auth.authorize(
            workspace_id=workspace_id, user=user
        )
        return await self.list_storyboards(workspace_id, session_id, user.id)

    async def update_storyboard(
        self, storyboard_id: int, storyboard_update: StoryboardUpdate
    ) -> StoryboardResponse | None:
        storyboard = await self.storyboard_repo.get_by_id_with_details(
            storyboard_id
        )
        if not storyboard:
            return None

        if storyboard_update.template_name is not None:
            await self.storyboard_repo.update(
                storyboard_id,
                {"template_name": storyboard_update.template_name},
            )

        if storyboard_update.bg_music_asset_id is not None:
            await self.storyboard_repo.update(
                storyboard_id,
                {"bg_music_asset_id": storyboard_update.bg_music_asset_id},
            )

        scenes_data = storyboard_update.scenes

        if storyboard_update.storyboard is not None:
            if scenes_data is None:
                scenes_data = storyboard_update.storyboard.get("scenes")

        if (
            scenes_data is not None
            or storyboard_update.bg_music_description is not None
        ):
            scenes_dto = None
            if scenes_data is not None:
                scenes_dto = []
                for idx, scene_data in enumerate(scenes_data):
                    first_frame_media_item_id = scene_data.get(
                        "first_frame_prompt", {}
                    ).get("media_item_id", None) or scene_data.get(
                        "first_frame_prompt", {}
                    ).get(
                        "asset_id"
                    )

                    video_media_item_id = scene_data.get(
                        "video_prompt", {}
                    ).get("media_item_id", None) or scene_data.get(
                        "video_prompt", {}
                    ).get(
                        "asset_id"
                    )

                    voiceover_media_item_id = scene_data.get(
                        "voiceover_prompt", {}
                    ).get("media_item_id", None) or scene_data.get(
                        "voiceover_prompt", {}
                    ).get(
                        "asset_id"
                    )

                    raw_scene_id = scene_data.get("scene_id")
                    scenes_dto.append(
                        SceneDTO(
                            scene_id=(
                                str(raw_scene_id)
                                if raw_scene_id not in (None, "")
                                else None
                            ),
                            order=idx,
                            topic=scene_data.get("topic"),
                            duration_seconds=scene_data.get("duration_seconds"),
                            first_frame_description=scene_data.get(
                                "first_frame_prompt", {}
                            ).get("description"),
                            first_frame_media_item_id=first_frame_media_item_id,
                            first_frame_source_asset_id=scene_data.get(
                                "first_frame_prompt", {}
                            ).get("source_asset_id"),
                            video_description=scene_data.get(
                                "video_prompt", {}
                            ).get("description"),
                            video_duration_seconds=scene_data.get(
                                "video_prompt", {}
                            ).get("duration_seconds"),
                            video_media_item_id=video_media_item_id,
                            video_source_asset_id=scene_data.get(
                                "video_prompt", {}
                            ).get("source_asset_id"),
                            video_generated_url=scene_data.get(
                                "video_prompt", {}
                            ).get("generated_url"),
                            voiceover_text=scene_data.get(
                                "voiceover_prompt", {}
                            ).get("text"),
                            voiceover_gender=scene_data.get(
                                "voiceover_prompt", {}
                            ).get("gender"),
                            voiceover_description=scene_data.get(
                                "voiceover_prompt", {}
                            ).get("description"),
                            voiceover_media_item_id=voiceover_media_item_id,
                            voiceover_source_asset_id=scene_data.get(
                                "voiceover_prompt", {}
                            ).get("source_asset_id"),
                            transition_type=scene_data.get(
                                "transition_hints", {}
                            ).get("type"),
                            transition_duration=scene_data.get(
                                "transition_hints", {}
                            ).get("duration"),
                            audio_ambient_description=scene_data.get(
                                "audio_hints", {}
                            ).get("ambient_sound"),
                            audio_sfx_description=scene_data.get(
                                "audio_hints", {}
                            ).get("sfx"),
                        )
                    )

            updated_storyboard = (
                await self.storyboard_repo.update_storyboard_data(
                    storyboard_id=storyboard_id,
                    bg_music_description=storyboard_update.bg_music_description,
                    scenes=scenes_dto,
                )
            )
            if updated_storyboard:
                await self._enrich_storyboard(updated_storyboard)
            return updated_storyboard

        refreshed = await self.storyboard_repo.get_by_id_with_details(
            storyboard_id
        )
        if refreshed:
            await self._enrich_storyboard(refreshed)
        return refreshed

    async def assign_scene_ids(
        self,
        storyboard_id: int,
        scenes: list[SceneDTO],
        scene_ids: list[str],
    ) -> dict[int, str]:
        """Stamps the agent's stable identities onto freshly saved scene rows.

        ``scene_ids`` is what the session sync resolved, one per scene in
        display order. Rows that already carry their id are left alone; the
        others are written and the DTOs patched in place, so the response
        the Workbench adopts carries them and the next edit matches by
        identity. Returns ``{row_id: scene_id}`` of what was written.
        """
        if len(scene_ids) != len(scenes):
            return {}
        assignments: dict[int, str] = {}
        for scene, scene_id in zip(scenes, scene_ids):
            if scene.id is None or not scene_id or scene.scene_id == scene_id:
                continue
            assignments[scene.id] = scene_id
        if not assignments:
            return {}
        await self.storyboard_repo.set_scene_ids(storyboard_id, assignments)
        for scene in scenes:
            if scene.id in assignments:
                scene.scene_id = assignments[scene.id]
        return assignments

    async def delete_storyboard(self, storyboard_id: int):
        await self.storyboard_repo.delete(storyboard_id)
