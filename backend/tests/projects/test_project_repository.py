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

"""StoryboardRepository and ProjectRepository queries."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from src.projects.project_repository import (
    ProjectRepository,
    StoryboardRepository,
)
from src.projects.schema.project_model import Project, Scene, Storyboard


@pytest.fixture(name="repo")
def fixture_repo(db_session_mock):
    db_session_mock.add = MagicMock()
    return StoryboardRepository(db=db_session_mock)


@pytest.fixture(name="project_repo")
def fixture_project_repo(db_session_mock):
    db_session_mock.add = MagicMock()
    return ProjectRepository(db=db_session_mock)


def _project_row(project_id=5, is_default=False):
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    return Project(
        id=project_id,
        workspace_id=10,
        owner_id=1,
        name="Spring",
        is_default=is_default,
        created_at=now,
        updated_at=now,
    )


def _pg(call) -> str:
    """Postgres SQL (with literals) of the statement passed to execute."""
    return str(
        call.args[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


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

    @pytest.mark.anyio
    async def test_find_by_workspace_filters_by_owner(
        self, repo, db_session_mock
    ):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db_session_mock.execute.return_value = result

        await repo.find_by_workspace(10, user_id=7)

        assert "storyboards.user_id = 7" in _compiled(
            db_session_mock.execute.await_args
        )

    @pytest.mark.anyio
    async def test_get_owner_and_project(self, repo, db_session_mock):
        result = MagicMock()
        result.first.return_value = (1, 5)
        db_session_mock.execute.return_value = result
        assert await repo.get_owner_and_project(14) == (1, 5)

        result.first.return_value = None
        assert await repo.get_owner_and_project(14) is None

    @pytest.mark.anyio
    async def test_session_ids_with_storyboards_is_owner_scoped(
        self, repo, db_session_mock
    ):
        result = MagicMock()
        result.scalars.return_value.all.return_value = ["s1"]
        db_session_mock.execute.return_value = result

        found = await repo.session_ids_with_storyboards(7, ["s1", "s2"])

        assert found == {"s1"}
        sql = _pg(db_session_mock.execute.await_args)
        assert "SELECT DISTINCT storyboards.session_id" in sql
        assert "storyboards.user_id = 7" in sql
        assert "storyboards.session_id IN ('s1', 's2')" in sql

    @pytest.mark.anyio
    async def test_session_ids_with_storyboards_without_ids(
        self, repo, db_session_mock
    ):
        assert await repo.session_ids_with_storyboards(7, []) == set()
        db_session_mock.execute.assert_not_called()

    @pytest.mark.anyio
    async def test_reassign_session_moves_only_the_owners_storyboards(
        self, repo, db_session_mock
    ):
        db_session_mock.execute.return_value = MagicMock(rowcount=2)

        moved = await repo.reassign_session("old", "new", 7)

        assert moved == 2
        sql = _pg(db_session_mock.execute.await_args)
        assert "UPDATE storyboards SET session_id='new'" in sql
        assert "storyboards.session_id = 'old'" in sql
        assert "storyboards.user_id = 7" in sql
        db_session_mock.commit.assert_awaited_once()


class TestProjectRepository:
    """Project summaries, creation and the idempotent default project."""

    @pytest.mark.anyio
    async def test_list_for_owner_attaches_the_summary(
        self, project_repo, db_session_mock
    ):
        result = MagicMock()
        result.all.return_value = [
            (_project_row(5, is_default=True), 2, "s9", None),
            (_project_row(6), None, None, 40),
        ]
        db_session_mock.execute.return_value = result

        projects = await project_repo.list_for_owner(10, 1)

        assert [p.id for p in projects] == [5, 6]
        assert projects[0].session_count == 2
        assert projects[0].latest_session_id == "s9"
        assert projects[1].session_count == 0
        assert projects[1].latest_timeline_id == 40
        sql = _pg(db_session_mock.execute.await_args)
        assert "projects.workspace_id = 10" in sql
        assert "projects.owner_id = 1" in sql
        assert "ORDER BY projects.is_default DESC, lower(projects.name)" in sql
        # Manual timelines only: no storyboard.
        assert "timelines.storyboard_id IS NULL" in sql
        assert "NULLS LAST" in sql

    @pytest.mark.anyio
    async def test_get_summary(self, project_repo, db_session_mock):
        result = MagicMock()
        result.first.return_value = (_project_row(5), 1, "s1", 3)
        db_session_mock.execute.return_value = result

        project = await project_repo.get_summary(5)
        assert project.latest_timeline_id == 3

        result.first.return_value = None
        assert await project_repo.get_summary(5) is None

    @pytest.mark.anyio
    async def test_create_project(self, project_repo, db_session_mock):
        async def _refresh(obj):
            obj.id = 9
            obj.created_at = obj.updated_at = datetime.now(timezone.utc)

        db_session_mock.refresh.side_effect = _refresh

        project = await project_repo.create_project(10, 1, "Spring")

        assert project.id == 9
        assert project.is_default is False
        added = db_session_mock.add.call_args.args[0]
        assert (added.workspace_id, added.owner_id) == (10, 1)
        db_session_mock.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_ensure_default_returns_an_existing_default(
        self, project_repo, db_session_mock
    ):
        result = MagicMock()
        result.scalar_one_or_none.return_value = _project_row(5, True)
        db_session_mock.execute.return_value = result

        project = await project_repo.ensure_default(10, 1)

        assert project.id == 5
        assert db_session_mock.execute.await_count == 1
        db_session_mock.commit.assert_not_called()

    @pytest.mark.anyio
    async def test_ensure_default_inserts_race_safely(
        self, project_repo, db_session_mock
    ):
        missing, found = MagicMock(), MagicMock()
        missing.scalar_one_or_none.return_value = None
        found.scalar_one_or_none.return_value = _project_row(5, True)
        db_session_mock.execute.side_effect = [missing, MagicMock(), found]

        project = await project_repo.ensure_default(10, 1)

        assert project.id == 5
        insert_sql = _pg(db_session_mock.execute.await_args_list[1])
        assert "INSERT INTO projects" in insert_sql
        assert "'Default project'" in insert_sql
        assert "ON CONFLICT DO NOTHING" in insert_sql
        db_session_mock.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_get_timeline_project(self, project_repo, db_session_mock):
        result = MagicMock()
        result.first.return_value = (5,)
        db_session_mock.execute.return_value = result
        assert await project_repo.get_timeline_project(42) == (True, 5)

        result.first.return_value = None
        assert await project_repo.get_timeline_project(42) == (False, None)
