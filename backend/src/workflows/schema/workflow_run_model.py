import datetime
from typing import Optional, Dict, Any

from sqlalchemy import String, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import Field

from src.database import Base
from src.common.base_repository import BaseStringDocument
from src.workflows.schema.workflow_model import WorkflowBase, WorkflowRunStatusEnum


class WorkflowRun(Base):
    """
    SQLAlchemy model for the 'workflow_runs' table.
    Stores the execution history and the snapshot of the workflow definition.
    """
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    workspace_id: Mapped[int] = mapped_column(nullable=True) # Denormalized if needed, or linked to workspace table? Keeping generic int for now.
    
    status: Mapped[str] = mapped_column(String, default=WorkflowRunStatusEnum.RUNNING.value, nullable=False)
    
    workflow_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )


class WorkflowRunModel(BaseStringDocument):
    """
    Pydantic model for Workflow Execution, including the snapshot.
    """
    workflow_id: str
    user_id: int
    workspace_id: Optional[int] = None
    status: WorkflowRunStatusEnum = Field(default=WorkflowRunStatusEnum.RUNNING)
    started_at: datetime.datetime
    completed_at: Optional[datetime.datetime] = None
    
    workflow_snapshot: Dict[str, Any]
