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

"""AgentSessionRepository: the chat -> project registry."""

import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from src.agents.agent_session_model import AgentSession
from src.agents.agent_session_repository import AgentSessionRepository


def _row(session_id="s1", project_id=5, user_id=1, workspace_id=10):
    return AgentSession(
        id=1,
        session_id=session_id,
        project_id=project_id,
        user_id=user_id,
        workspace_id=workspace_id,
        app_name="ads_x",
        title="Spring launch",
    )


def _sql(call) -> str:
    """Postgres SQL of the statement passed to ``db.execute``."""
    return str(
        call.args[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def _result_with(row=None, rows=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    result.scalars.return_value.all.return_value = rows or []
    return result


@pytest.fixture(name="repo")
def fixture_repo(db_session_mock):
    return AgentSessionRepository(db=db_session_mock)


class TestAgentSessionRepository:
    """The SQL each registry method sends (Postgres dialect)."""

    @pytest.mark.anyio
    async def test_get_filters_by_session_id(self, repo, db_session_mock):
        db_session_mock.execute.return_value = _result_with(row=_row())

        row = await repo.get("s1")

        assert row.session_id == "s1"
        assert "agent_sessions.session_id = 's1'" in _sql(
            db_session_mock.execute.call_args
        )

    @pytest.mark.anyio
    async def test_register_is_idempotent_and_returns_the_row(
        self, repo, db_session_mock
    ):
        db_session_mock.execute.side_effect = [
            MagicMock(),
            _result_with(row=_row()),
        ]

        row = await repo.register("s1", 5, 1, 10, "ads_x")

        insert_sql = _sql(db_session_mock.execute.call_args_list[0])
        assert "INSERT INTO agent_sessions" in insert_sql
        assert "ON CONFLICT (session_id) DO NOTHING" in insert_sql
        db_session_mock.commit.assert_awaited()
        assert row.project_id == 5

    @pytest.mark.anyio
    async def test_register_marks_only_a_restored_chat(
        self, repo, db_session_mock
    ):
        db_session_mock.execute.side_effect = [
            MagicMock(),
            _result_with(row=_row()),
            MagicMock(),
            _result_with(row=_row()),
        ]

        await repo.register("s1", 5, 1, 10, "ads_x")
        await repo.register("s1", 5, 1, 10, "ads_x", restored=True)

        calls = db_session_mock.execute.call_args_list
        # VALUES end with last_used_at, restored_at.
        assert "now(), NULL)" in _sql(calls[0])
        assert "now(), now())" in _sql(calls[2])

    @pytest.mark.anyio
    async def test_adopt_inserts_unique_ids_once(self, repo, db_session_mock):
        await repo.adopt(["a", "b", "a", ""], 5, 1, 10)

        sql = _sql(db_session_mock.execute.call_args)
        assert sql.count("'a'") == 1
        assert "'b'" in sql
        assert "ON CONFLICT (session_id) DO NOTHING" in sql
        db_session_mock.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_adopt_without_ids_does_nothing(self, repo, db_session_mock):
        await repo.adopt([], 5, 1, 10)

        db_session_mock.execute.assert_not_called()
        db_session_mock.commit.assert_not_called()

    @pytest.mark.anyio
    async def test_adopt_records_the_listed_activity(
        self, repo, db_session_mock
    ):
        used_at = datetime.datetime(2026, 10, 1, 12, tzinfo=datetime.UTC)

        await repo.adopt(["a", "b"], 5, 1, 10, last_used={"a": used_at})

        params = (
            db_session_mock.execute.call_args.args[0]
            .compile(dialect=postgresql.dialect())
            .params
        )
        by_session = {
            params[f"session_id_m{i}"]: params[f"last_used_at_m{i}"]
            for i in range(2)
        }
        # "b" has no listed activity: it stays NULL.
        assert by_session == {"a": used_at, "b": None}

    @pytest.mark.anyio
    async def test_seed_last_used_fills_only_missing_activity(
        self, repo, db_session_mock
    ):
        used_at = datetime.datetime(2026, 10, 2, 9, 30, tzinfo=datetime.UTC)

        await repo.seed_last_used(1, {"s1": used_at})

        sql = _sql(db_session_mock.execute.call_args)
        assert "SET last_used_at=CASE agent_sessions.session_id" in sql
        assert "WHEN 's1' THEN CAST(" in sql
        assert "AS TIMESTAMP WITH TIME ZONE)" in sql
        # Never another user's row, never a recorded activity.
        assert "agent_sessions.user_id = 1" in sql
        assert "agent_sessions.session_id IN ('s1')" in sql
        assert "agent_sessions.last_used_at IS NULL" in sql
        db_session_mock.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_seed_last_used_without_times_does_nothing(
        self, repo, db_session_mock
    ):
        await repo.seed_last_used(1, {})

        db_session_mock.execute.assert_not_called()
        db_session_mock.commit.assert_not_called()

    @pytest.mark.anyio
    async def test_map_for_user_workspace_is_keyed_by_session(
        self, repo, db_session_mock
    ):
        db_session_mock.execute.return_value = _result_with(
            rows=[_row("s1"), _row("s2")]
        )

        mapping = await repo.map_for_user_workspace(1, 10)

        assert set(mapping) == {"s1", "s2"}
        sql = _sql(db_session_mock.execute.call_args)
        assert "agent_sessions.user_id = 1" in sql
        assert "agent_sessions.workspace_id = 10" in sql

    @pytest.mark.anyio
    async def test_app_names_for_project(self, repo, db_session_mock):
        result = MagicMock()
        result.all.return_value = [("s1", "ads_x"), ("s2", "brand_x")]
        db_session_mock.execute.return_value = result

        assert await repo.app_names_for_project(5) == {
            "s1": "ads_x",
            "s2": "brand_x",
        }
        sql = _sql(db_session_mock.execute.call_args)
        assert "agent_sessions.app_name" in sql
        assert "agent_sessions.project_id = 5" in sql

    @pytest.mark.anyio
    async def test_update_metadata_sets_only_given_fields(
        self, repo, db_session_mock
    ):
        row = _row()
        db_session_mock.execute.side_effect = [
            MagicMock(),
            _result_with(row=row),
        ]

        updated = await repo.update_metadata("s1", title="New title")

        sql = _sql(db_session_mock.execute.call_args_list[0])
        assert "title='New title'" in sql
        assert "summary" not in sql
        db_session_mock.refresh.assert_awaited_once_with(row)
        assert updated is row

    @pytest.mark.anyio
    async def test_update_metadata_without_values_only_reads(
        self, repo, db_session_mock
    ):
        db_session_mock.execute.return_value = _result_with(row=None)

        assert await repo.update_metadata("s1") is None
        db_session_mock.commit.assert_not_called()
        db_session_mock.refresh.assert_not_called()

    @pytest.mark.anyio
    async def test_update_metadata_summary_only_keeps_the_title(
        self, repo, db_session_mock
    ):
        db_session_mock.execute.side_effect = [
            MagicMock(),
            _result_with(row=_row()),
        ]

        await repo.update_metadata("s1", summary="Teaser cut")

        sql = _sql(db_session_mock.execute.call_args_list[0])
        assert "summary='Teaser cut'" in sql
        assert "title" not in sql

    @pytest.mark.anyio
    async def test_replace_session_id_reports_whether_a_row_moved(
        self, repo, db_session_mock
    ):
        db_session_mock.execute.return_value = MagicMock(rowcount=1)
        assert await repo.replace_session_id("old", "new", 1) is True
        sql = _sql(db_session_mock.execute.call_args)
        assert "session_id='new'" in sql
        assert "restored_at=now()" in sql
        assert "agent_sessions.user_id = 1" in sql

        db_session_mock.execute.return_value = MagicMock(rowcount=0)
        assert await repo.replace_session_id("old", "new", 1) is False

    @pytest.mark.anyio
    async def test_replace_session_id_can_leave_the_restored_mark(
        self, repo, db_session_mock
    ):
        db_session_mock.execute.return_value = MagicMock(rowcount=1)

        await repo.replace_session_id("old", "new", 1, restored=False)

        sql = _sql(db_session_mock.execute.call_args)
        assert "session_id='new'" in sql
        assert "restored_at" not in sql

    @pytest.mark.anyio
    async def test_touch_and_delete(self, repo, db_session_mock):
        await repo.touch("s1", 1)
        touch_sql = _sql(db_session_mock.execute.call_args)
        assert "last_used_at=now()" in touch_sql
        assert "agent_sessions.session_id = 's1'" in touch_sql
        assert "agent_sessions.user_id = 1" in touch_sql

        await repo.delete("s1")
        assert "DELETE FROM agent_sessions" in _sql(
            db_session_mock.execute.call_args
        )
        assert db_session_mock.commit.await_count == 2
