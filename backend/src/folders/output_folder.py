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

"""Picks the gallery folder a newly generated media item is saved into.

Precedence: an explicit ``folder_id`` from the request wins, then the Izumi
agent folder (see :mod:`src.folders.agent_output_folder`), then the
workspace root (``None``).

An explicit folder must exist, must not be soft-deleted and must belong to
the request's workspace. There is no owner check, matching the gallery
"move items" rule: any member allowed to generate in the workspace may save
into any of its folders. Missing, deleted and foreign folders share one
generic error so folder ids cannot be enumerated across workspaces.
"""

import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.folders.agent_output_folder import resolve_agent_output_folder_id
from src.folders.repository.folder_repository import FolderRepository
from src.users.user_model import UserModel

logger = logging.getLogger(__name__)

OUTPUT_FOLDER_NOT_FOUND_DETAIL = (
    "The selected output folder was not found in this workspace."
)


async def resolve_output_folder_id(
    db: AsyncSession,
    workspace_id: int,
    user: UserModel,
    requested_folder_id: int | None,
) -> int | None:
    """Returns the folder id for a new media item placeholder.

    Raises:
        HTTPException: 422 when ``requested_folder_id`` does not point to an
            active folder of ``workspace_id``.
    """
    if requested_folder_id is None:
        return await resolve_agent_output_folder_id(db, workspace_id, user)

    folder = await FolderRepository(db).get_folder_by_id(requested_folder_id)
    if folder is None or folder.workspace_id != workspace_id:
        logger.warning(
            "User %s requested output folder %s, which is not an active "
            "folder of workspace %s",
            user.id,
            requested_folder_id,
            workspace_id,
        )
        raise HTTPException(
            status_code=422,
            detail=OUTPUT_FOLDER_NOT_FOUND_DETAIL,
        )
    return requested_folder_id
