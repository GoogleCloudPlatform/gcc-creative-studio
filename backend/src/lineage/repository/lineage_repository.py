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
"""Repository for writing and traversing polymorphic item lineage edges."""

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.lineage.lineage_builder import LineageEdgeSpec
from src.lineage.schema.item_lineage_model import (
    ItemLineage,
    LineageItemTypeEnum,
)


@dataclass(frozen=True)
class AncestorChainRow:
    """One primary edge from the recursive ancestor CTE (root -> leaf)."""

    id: int
    child_type: str
    child_id: int
    child_index: int | None
    parent_type: str
    parent_id: int
    parent_index: int
    role: str
    action_summary: str | None
    depth: int


class LineageRepository:
    """Persistence and graph traversal queries for ``item_lineage``."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def has_any_edges_for_child(
        self,
        *,
        workspace_id: int,
        child_type: LineageItemTypeEnum,
        child_id: int,
    ) -> bool:
        """Returns True if the child item already has any recorded edge."""
        stmt = (
            select(ItemLineage.id)
            .where(
                ItemLineage.workspace_id == workspace_id,
                ItemLineage.child_type == child_type.value,
                ItemLineage.child_id == child_id,
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def replace_child_edges(
        self,
        *,
        workspace_id: int,
        child_type: LineageItemTypeEnum,
        child_id: int,
        edges: Sequence[LineageEdgeSpec],
    ) -> None:
        """Idempotently replaces all incoming edges for a child item."""
        await self.db.execute(
            delete(ItemLineage).where(
                ItemLineage.workspace_id == workspace_id,
                ItemLineage.child_type == child_type.value,
                ItemLineage.child_id == child_id,
            )
        )
        rows = [
            {
                "workspace_id": workspace_id,
                "child_type": child_type.value,
                "child_id": child_id,
                "child_index": edge.child_index,
                "parent_type": edge.parent_type.value,
                "parent_id": edge.parent_id,
                "parent_index": edge.parent_index,
                "role": edge.role,
                "is_primary_parent": edge.is_primary_parent,
                "action_summary": edge.action_summary,
            }
            for edge in edges
            if not (
                edge.parent_type == child_type and edge.parent_id == child_id
            )
        ]
        if rows:
            await self.db.execute(insert(ItemLineage).values(rows))
        await self.db.commit()

    async def get_primary_ancestor_chain(
        self,
        *,
        workspace_id: int,
        item_type: LineageItemTypeEnum,
        item_id: int,
        max_depth: int = 25,
    ) -> list[AncestorChainRow]:
        """Walks ``is_primary_parent = TRUE`` edges upward with cycle guard.

        Returns rows ordered from oldest ancestor edge (``root -> step 2``)
        down to the immediate parent edge (``parent -> item``).
        """
        cte_query = text(
            """
            WITH RECURSIVE primary_chain AS (
                SELECT
                    il.id,
                    il.child_type,
                    il.child_id,
                    il.child_index,
                    il.parent_type,
                    il.parent_id,
                    il.parent_index,
                    il.role,
                    il.action_summary,
                    1 AS depth,
                    ARRAY[
                        il.child_type || ':' || il.child_id::text,
                        il.parent_type || ':' || il.parent_id::text
                    ] AS visited
                FROM item_lineage il
                WHERE il.workspace_id = :workspace_id
                  AND il.child_type = :item_type
                  AND il.child_id = :item_id
                  AND il.is_primary_parent = TRUE
                UNION ALL
                SELECT
                    p_il.id,
                    p_il.child_type,
                    p_il.child_id,
                    p_il.child_index,
                    p_il.parent_type,
                    p_il.parent_id,
                    p_il.parent_index,
                    p_il.role,
                    p_il.action_summary,
                    pc.depth + 1,
                    pc.visited || (
                        p_il.parent_type || ':' || p_il.parent_id::text
                    )
                FROM item_lineage p_il
                JOIN primary_chain pc
                  ON p_il.workspace_id = :workspace_id
                 AND p_il.child_type = pc.parent_type
                 AND p_il.child_id = pc.parent_id
                 AND p_il.is_primary_parent = TRUE
                WHERE pc.depth < :max_depth
                  AND NOT (
                      (p_il.parent_type || ':' || p_il.parent_id::text)
                      = ANY(pc.visited)
                  )
            )
            SELECT
                id,
                child_type,
                child_id,
                child_index,
                parent_type,
                parent_id,
                parent_index,
                role,
                action_summary,
                depth
            FROM primary_chain
            ORDER BY depth DESC;
            """
        )
        result = await self.db.execute(
            cte_query,
            {
                "workspace_id": workspace_id,
                "item_type": item_type.value,
                "item_id": item_id,
                "max_depth": max_depth,
            },
        )
        return [
            AncestorChainRow(
                id=row.id,
                child_type=row.child_type,
                child_id=row.child_id,
                child_index=row.child_index,
                parent_type=row.parent_type,
                parent_id=row.parent_id,
                parent_index=row.parent_index,
                role=row.role,
                action_summary=row.action_summary,
                depth=row.depth,
            )
            for row in result.fetchall()
        ]

    async def get_direct_derivative_edges(
        self,
        *,
        workspace_id: int,
        parent_type: LineageItemTypeEnum,
        parent_id: int,
        limit: int = 50,
    ) -> list[ItemLineage]:
        """Returns direct child edges derived from the given parent item."""
        stmt = (
            select(ItemLineage)
            .where(
                ItemLineage.workspace_id == workspace_id,
                ItemLineage.parent_type == parent_type.value,
                ItemLineage.parent_id == parent_id,
            )
            .order_by(ItemLineage.created_at.asc(), ItemLineage.id.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
