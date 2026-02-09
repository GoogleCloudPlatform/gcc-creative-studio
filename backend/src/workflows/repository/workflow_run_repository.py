from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseStringRepository
from src.database import get_db
from src.workflows.schema.workflow_run_model import WorkflowRun, WorkflowRunModel


class WorkflowRunRepository(BaseStringRepository[WorkflowRun, WorkflowRunModel]):
    """
    Repository for WorkflowRun.
    """

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(WorkflowRun, WorkflowRunModel, db)
