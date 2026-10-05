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

"""StoryboardRepository: newest-first listing and session lookup."""

from unittest.mock import MagicMock

import pytest

from src.projects.project_repository import StoryboardRepository
from src.projects.schema.project_model import Scene, Storyboard


@pytest.fixture(name="repo")
def fixture_repo(db_session_mock):
    db_session_mock.add = MagicMock()
    return StoryboardRepository(db=db_session_mock)


def _row(storyboard_id, session_id="s1"):
    row = Storyboard(
        id=storyboard_id,
        user_id=1,
        workspace_id=10,
        session_id=session_id,
        template_name="Custom",
    )
    row.scenes = [
        Scene(id=storyboard_id * 10, scene_id="a", order=0, topic="Hook")
    ]
    row.timeline = None
    return row


def _compiled(call):
    """SQL text of the statement passed to ``db.execute``."""
    return str(call.args[0].compile(compile_kwargs={"literal_binds": True}))


class TestStoryboardRepository:
    @pytest.mark.anyio
    async def test_find_by_workspace_orders_newest_first(
        self, repo, db_session_mock
    ):
        result = MagicMock()
        result.scalars.return_value.all.return_value = [_row(14), _row(13)]
        db_session_mock.execute.return_value = result

        items = await repo.find_by_workspace(10, session_id="s1")

        assert [i.id for i in items] == [14, 13]
        assert items[0].scenes[0].scene_id == "a"
        assert items[0].scenes[0].order == 0
        sql = _compiled(db_session_mock.execute.await_args)
        assert "ORDER BY storyboards.id DESC" in sql
        assert "storyboards.session_id" in sql

    @pytest.mark.anyio
    async def test_find_latest_by_session(self, repo, db_session_mock):
        result = MagicMock()
        result.scalar_one_or_none.return_value = _row(14)
        db_session_mock.execute.return_value = result

        found = await repo.find_latest_by_session(10, "s1", 1)

        assert found.id == 14
        assert found.session_id == "s1"
        sql = _compiled(db_session_mock.execute.await_args)
        assert "ORDER BY storyboards.id DESC" in sql
        assert "LIMIT 1" in sql
        assert "storyboards.user_id = 1" in sql

    @pytest.mark.anyio
    async def test_find_latest_by_session_none(self, repo, db_session_mock):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db_session_mock.execute.return_value = result
        assert await repo.find_latest_by_session(10, "s1", 1) is None

    @pytest.mark.anyio
    async def test_set_scene_ids_updates_rows_pinned_to_storyboard(
        self, repo, db_session_mock
    ):
        await repo.set_scene_ids(
            14, {140: "scene-01-hook", 141: "scene-02-mist"}
        )

        assert db_session_mock.execute.await_count == 2
        statements = [
            _compiled(call) for call in db_session_mock.execute.await_args_list
        ]
        assert "UPDATE scenes SET scene_id='scene-01-hook'" in statements[0]
        assert "scenes.id = 140" in statements[0]
        assert "scenes.storyboard_id = 14" in statements[0]
        assert "UPDATE scenes SET scene_id='scene-02-mist'" in statements[1]
        assert "scenes.id = 141" in statements[1]
        db_session_mock.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_set_scene_ids_without_assignments_is_a_no_op(
        self, repo, db_session_mock
    ):
        await repo.set_scene_ids(14, {})
        db_session_mock.execute.assert_not_called()
        db_session_mock.commit.assert_not_called()
