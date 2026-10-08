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

import datetime
import inspect
import logging
import math
from typing import Any
import uuid

from fastapi import Depends
from google.api_core.exceptions import InvalidArgument, NotFound
from google.cloud import workflows_v1
from google.cloud.workflows import executions_v1
from pydantic import ValidationError

from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.common.secret_redaction import install_secret_redaction
from src.config.config_service import config_service
from src.images.imagen_service import ImagenService
from src.source_assets.source_asset_service import SourceAssetService
from src.users.user_model import UserModel
from src.workflows.dto.batch_execution_dto import (
    BatchExecutionRequestDto,
    BatchExecutionResponseDto,
    BatchItemResultDto,
)
from src.workflows.dto.workflow_run_dto import (
    WorkflowRunDetailDto,
    WorkflowRunSummaryDto,
)
from src.workflows.dto.workflow_search_dto import WorkflowSearchDto
from src.workflows.queue.run_state_service import (
    DispatchHook,
    RunStateService,
    get_dispatch_hook,
)
from src.workflows.repository.workflow_repository import WorkflowRepository
from src.workflows.repository.workflow_run_repository import (
    WorkflowRunRepository,
)
from src.workflows.repository.workflow_template_repository import (
    WorkflowTemplateRepository,
)
from src.workflows.schema.workflow_model import (
    WorkflowBase,
    WorkflowCreateDto,
    WorkflowModel,
    WorkflowRunStatusEnum,
)
from src.workflows.schema.workflow_run_model import (
    QueueReasonEnum,
    StepState,
    WorkflowRunModel,
)
from src.workflows.schema.workflow_template_model import (
    WorkflowTemplateCreateDto,
    WorkflowTemplateModel,
)
from src.workflows.run_step_entries import build_step_entries
from src.workflows.workflow_utils import interpolate_prompt_variables
from src.workflows.workflow_yaml_builder import (
    RESERVED_ARGS,
    build_workflow_yaml,
    compute_definition_hash,
    initial_step_states,
)

logger = install_secret_redaction(logging.getLogger(__name__))
PROJECT_ID = config_service.PROJECT_ID
LOCATION = config_service.WORKFLOWS_LOCATION
BACKEND_EXECUTOR_URL = config_service.WORKFLOWS_EXECUTOR_URL


class WorkflowConflictError(Exception):
    """Raised (HTTP 409) when editing or deleting a workflow with active runs."""


class WorkflowService:
    """Orchestrates multi-step generative AI workflows."""

    def __init__(
        self,
        workflow_repository: WorkflowRepository = Depends(),
        workflow_run_repository: WorkflowRunRepository = Depends(),
        source_asset_service: SourceAssetService = Depends(),
        workflow_template_repository: WorkflowTemplateRepository = Depends(),
    ):
        self.imagen_service = ImagenService()
        self.workflow_repository = workflow_repository
        self.workflow_run_repository = workflow_run_repository
        self.source_asset_service = source_asset_service
        self.workflow_template_repository = workflow_template_repository
        self.run_state_service = RunStateService(
            repository=workflow_run_repository,
        )
        self._dispatch_hook: DispatchHook | None = None

    def _generate_workflow_yaml(
        self,
        workflow: WorkflowModel,
    ) -> str:
        """Generates the GCP Workflows YAML of ``workflow``."""
        logger.info(
            "Received workflow generation request for user %s",
            workflow.user_id,
        )
        return build_workflow_yaml(
            workflow.steps,
            executor_url=config_service.WORKFLOWS_EXECUTOR_URL,
            step_timeout_seconds=(
                config_service.WORKFLOW_STEP_HTTP_TIMEOUT_SECONDS
            ),
        )

    def validate_workflow(
        self,
        workflow_dto: WorkflowBase,
        user: UserModel,
    ) -> dict[str, Any]:
        """Validates workflow definition and steps structure without persisting to database or GCP."""
        transient_workflow = WorkflowModel(
            id="validation-temp",
            user_id=user.id,
            name=workflow_dto.name,
            description=workflow_dto.description,
            steps=workflow_dto.steps,
        )
        try:
            self._generate_workflow_yaml(transient_workflow)
        except Exception as e:
            logger.error("Workflow validation failed: %s", e)
            raise ValueError(f"Invalid workflow structure: {str(e)}")
        return {"valid": True, "message": "Workflow structure is valid."}

    def _create_gcp_workflow(self, source_contents: str, workflow_id: str):
        client = workflows_v1.WorkflowsClient()

        # Initialize request argument(s)
        workflow = workflows_v1.Workflow()
        workflow.source_contents = source_contents
        workflow.execution_history_level = (
            workflows_v1.ExecutionHistoryLevel.EXECUTION_HISTORY_DETAILED
        )
        if config_service.BACKEND_SERVICE_ACCOUNT_EMAIL:
            workflow.service_account = (
                config_service.BACKEND_SERVICE_ACCOUNT_EMAIL
            )

        request = workflows_v1.CreateWorkflowRequest(
            parent=f"projects/{PROJECT_ID}/locations/{LOCATION}",
            workflow=workflow,
            workflow_id=workflow_id,
        )

        try:
            operation = client.create_workflow(request=request)
            response = operation.result()
            return response
        except InvalidArgument as e:
            raise ValueError(str(e))

    def _update_gcp_workflow(self, source_contents: str, workflow_id: str):
        client = workflows_v1.WorkflowsClient()

        # Initialize request argument(s)
        workflow = workflows_v1.Workflow(
            name=f"projects/{PROJECT_ID}/locations/{LOCATION}/workflows/{workflow_id}",
        )
        workflow.source_contents = source_contents
        workflow.execution_history_level = (
            workflows_v1.ExecutionHistoryLevel.EXECUTION_HISTORY_DETAILED
        )
        if config_service.BACKEND_SERVICE_ACCOUNT_EMAIL:
            workflow.service_account = (
                config_service.BACKEND_SERVICE_ACCOUNT_EMAIL
            )

        request = workflows_v1.UpdateWorkflowRequest(
            workflow=workflow,
        )

        try:
            operation = client.update_workflow(request=request)
            response = operation.result()
            return response
        except InvalidArgument as e:
            raise ValueError(str(e))

    def _delete_gcp_workflow(self, workflow_id: str):
        client = workflows_v1.WorkflowsClient()

        # Construct the fully qualified location path.
        parent = client.workflow_path(
            config_service.PROJECT_ID,
            config_service.WORKFLOWS_LOCATION,
            workflow_id,
        )

        request = workflows_v1.DeleteWorkflowRequest(
            name=parent,
        )

        try:
            operation = client.delete_workflow(request=request)
            response = operation.result()
            logger.info(
                f"Deleted GCP workflow for id '{workflow_id}' with response '{response}'",
            )
            return response
        except NotFound:
            logger.warning(
                f"Workflow '{workflow_id}' not found in GCP. Proceeding with local deletion.",
            )
            return None

    async def create_workflow(
        self,
        workflow_dto: WorkflowCreateDto,
        user: UserModel,
    ) -> WorkflowModel:
        """Creates a new workflow definition."""
        try:
            # 1. Generate the ID manually
            workflow_id = f"id-{uuid.uuid4()}"

            # 2. Create the workflow in the database
            workflow_model = WorkflowModel(
                id=workflow_id,
                user_id=user.id,
                name=workflow_dto.name,
                description=workflow_dto.description,
                steps=workflow_dto.steps,
            )
            created_workflow = await self.workflow_repository.create(
                workflow_model
            )

            # 3. Generate GCP Workflow YAML (using the same ID)
            yaml_output = self._generate_workflow_yaml(created_workflow)
            logger.info("Generated YAML:")
            logger.info(yaml_output)

            # 4. Create GCP Workflow
            try:
                self._create_gcp_workflow(yaml_output, workflow_id)
            except Exception as e:
                # Rollback DB creation if GCP creation fails
                logger.error(
                    "Failed to create GCP workflow: %s. Rolling back DB.", e
                )
                await self.workflow_repository.delete(created_workflow.id)
                raise e

            return created_workflow
        except ValidationError as e:
            raise ValueError(str(e))
        except Exception as e:
            # TODO: Improve error handling here
            logging.exception(e)
            raise e

    async def get_workflow(self, user_id: int, workflow_id: str):
        #  Add logic here if needed before fetching from repository
        workflow = await self.workflow_repository.get_by_id(workflow_id)
        if workflow and workflow.user_id == user_id:
            return workflow
        return None

    async def get_by_id(self, workflow_id: str) -> WorkflowModel | None:
        """Retrieves a workflow by its ID without any authorization checks."""
        return await self.workflow_repository.get_by_id(workflow_id)

    async def query_workflows(
        self,
        user_id: int,
        search_dto: WorkflowSearchDto,
    ) -> PaginationResponseDto[WorkflowModel]:
        return await self.workflow_repository.query(user_id, search_dto)

    async def _ensure_no_active_runs(self, workflow_id: str) -> None:
        """Raises :class:`WorkflowConflictError` if ``workflow_id`` has active runs."""
        active_count = (
            await self.workflow_run_repository.count_active_by_workflow(
                workflow_id
            )
        )
        if active_count > 0:
            raise WorkflowConflictError(
                "Cannot modify or delete workflow while runs are queued or "
                "running. Please wait for active runs to finish or cancel "
                "them first."
            )

    async def update_workflow(
        self,
        workflow_id: str,
        workflow_dto: WorkflowCreateDto,
        user: UserModel,
    ) -> WorkflowModel | None:
        """Validates and updates a workflow, rejecting edits while runs are active (Q1)."""
        await self._ensure_no_active_runs(workflow_id)
        try:
            # Create the full model from the DTO, preserving the existing ID and user.
            updated_model = WorkflowModel(
                id=workflow_id,
                user_id=user.id,
                name=workflow_dto.name,
                description=workflow_dto.description,
                steps=workflow_dto.steps,
            )

            yaml_output = self._generate_workflow_yaml(updated_model)
            logger.info("Generated YAML for update:")
            logger.info(yaml_output)

            # The GCP workflow ID matches the DB ID (which is already in the format id-UUID)
            self._update_gcp_workflow(yaml_output, workflow_id)

            return await self.workflow_repository.update(
                workflow_id, updated_model
            )
        except ValidationError as e:
            raise ValueError(str(e))

    async def delete_by_id(self, workflow_id: str) -> bool:
        """Deletes a workflow from the system, rejecting deletion while runs are active."""
        await self._ensure_no_active_runs(workflow_id)
        # The GCP workflow ID matches the DB ID
        self._delete_gcp_workflow(workflow_id)
        response = await self.workflow_repository.delete(workflow_id)
        return response

    async def submit_run(
        self,
        workflow_id: str,
        args: dict[str, Any] | None,
        user: UserModel,
        *,
        trigger_dispatch: bool = True,
    ) -> WorkflowRunModel:
        """Inserts a ``QUEUED`` workflow run and optionally triggers the dispatcher.

        Never persists ``user_auth_header`` in ``input_args``. Raises on DB
        errors.
        """
        workflow_model = await self.get_by_id(workflow_id)
        if not workflow_model:
            raise ValueError(f"Workflow {workflow_id} not found")

        raw_args = dict(args or {})
        cleaned_args = {
            k: v
            for k, v in raw_args.items()
            if k not in RESERVED_ARGS and k != "user_token"
        }
        workspace_id = cleaned_args.get("workspace_id")
        if workspace_id is not None:
            try:
                workspace_id = int(workspace_id)
                cleaned_args["workspace_id"] = workspace_id
            except (TypeError, ValueError):
                workspace_id = None

        snapshot_data = workflow_model.model_dump(
            mode="json",
            exclude={"created_at", "updated_at"},
        )
        def_hash = compute_definition_hash(workflow_model.steps)
        step_states = {
            step_id: StepState.model_validate(state_dict)
            for step_id, state_dict in initial_step_states(
                workflow_model.steps
            ).items()
        }

        now = datetime.datetime.now(datetime.UTC)
        run_id = str(uuid.uuid4())
        workflow_run = WorkflowRunModel(
            id=run_id,
            workflow_id=workflow_id,
            user_id=user.id,
            workspace_id=workspace_id,
            status=WorkflowRunStatusEnum.QUEUED,
            queue_reason=QueueReasonEnum.WAITING_FOR_SLOT,
            started_at=now,
            queued_at=now,
            workflow_snapshot=snapshot_data,
            input_args=cleaned_args,
            definition_hash=def_hash,
            step_states=step_states,
            attempt_count=0,
        )
        created_run = await self.workflow_run_repository.create(workflow_run)
        if not isinstance(created_run, WorkflowRunModel):
            created_run = workflow_run

        if trigger_dispatch:
            await self._trigger_dispatch("submit", user.id)
            refreshed = await self.workflow_run_repository.get_by_id(run_id)
            if isinstance(refreshed, WorkflowRunModel):
                return refreshed
        return created_run

    async def execute_workflow(
        self,
        workflow_id: str,
        args: dict[str, Any],
        user: UserModel,
    ) -> WorkflowRunModel:
        """Submits a workflow run to the queue and triggers inline dispatch."""
        return await self.submit_run(
            workflow_id=workflow_id,
            args=args,
            user=user,
            trigger_dispatch=True,
        )

    async def batch_execute_workflow(
        self,
        workflow_id: str,
        batch_dto: BatchExecutionRequestDto,
        user: UserModel,
    ) -> BatchExecutionResponseDto:
        """Queues a workflow run for each item in the batch request and triggers dispatch once."""
        if not batch_dto.items:
            return BatchExecutionResponseDto(results=[])

        async def process_row(item: Any) -> BatchItemResultDto:
            try:
                processed_args: dict[str, Any] = {}
                workspace_id = item.args.get("workspace_id")

                for key, value in item.args.items():
                    is_gcs_string = isinstance(value, str) and value.startswith(
                        "gs://"
                    )
                    is_gcs_list = (
                        isinstance(value, list)
                        and len(value) > 0
                        and isinstance(value[0], str)
                        and value[0].startswith("gs://")
                    )

                    if is_gcs_string or is_gcs_list:
                        try:
                            if not workspace_id:
                                raise ValueError(
                                    "No workspace_id provided for GCS ingestion.",
                                )

                            w_id = int(workspace_id)
                            uris = [value] if is_gcs_string else value

                            assets = [
                                await self.source_asset_service.create_from_gcs_uri(
                                    user=user,
                                    workspace_id=w_id,
                                    gcs_uri=uri,
                                )
                                for uri in uris
                            ]

                            ingested_results = [
                                {"sourceAssetId": asset.id, "previewUrl": uri}
                                for asset, uri in zip(assets, uris)
                            ]

                            processed_args[key] = (
                                ingested_results[0]
                                if is_gcs_string
                                else ingested_results
                            )

                        except Exception as e:
                            await self._rollback_if_needed()
                            logger.exception(
                                "Failed to ingest GCS URI in '%s': %s from row %s",
                                key,
                                e,
                                item.row_index,
                            )
                            return BatchItemResultDto(
                                row_index=item.row_index,
                                status="FAILED",
                                run_status="FAILED",
                                error=f"Invalid GCS URI in '{key}': {e!s}",
                            )
                    else:
                        processed_args[key] = value

                run = await self.submit_run(
                    workflow_id=workflow_id,
                    args=processed_args,
                    user=user,
                    trigger_dispatch=False,
                )
                return BatchItemResultDto(
                    row_index=item.row_index,
                    run_id=run.id,
                    execution_id=run.id,
                    status="SUCCESS",
                    run_status=WorkflowRunStatusEnum(run.status).value,
                    queue_reason=(
                        QueueReasonEnum(run.queue_reason).value
                        if run.queue_reason is not None
                        else None
                    ),
                )
            except Exception as e:  # pylint: disable=broad-exception-caught
                await self._rollback_if_needed()
                return BatchItemResultDto(
                    row_index=item.row_index,
                    status="FAILED",
                    run_status="FAILED",
                    error=str(e),
                )

        results = [await process_row(item) for item in batch_dto.items]

        if any(r.status == "SUCCESS" for r in results):
            await self._trigger_dispatch("batch_submit", user.id)
            for item_res in results:
                if item_res.status == "SUCCESS" and item_res.run_id:
                    refreshed = await self.workflow_run_repository.get_by_id(
                        item_res.run_id
                    )
                    if isinstance(refreshed, WorkflowRunModel):
                        item_res.run_status = WorkflowRunStatusEnum(
                            refreshed.status
                        ).value
                        item_res.queue_reason = (
                            QueueReasonEnum(refreshed.queue_reason).value
                            if refreshed.queue_reason is not None
                            else None
                        )

        return BatchExecutionResponseDto(results=results)

    @staticmethod
    def _interpolate_prompt_variables(
        prompt: str,
        step_inputs: dict[str, Any],
    ) -> str:
        """Interpolates <var_name> placeholders in prompt using step inputs."""
        return interpolate_prompt_variables(
            prompt=prompt,
            variables=step_inputs,
            keep_unresolved=True,
        )

    async def list_runs(
        self,
        workflow_id: str,
        user_id: int,
        *,
        status: WorkflowRunStatusEnum | str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> PaginationResponseDto[WorkflowRunSummaryDto]:
        """Lists DB workflow runs for ``workflow_id`` owned by ``user_id`` (§9.2, Q4)."""
        items, total = await self.workflow_run_repository.list_by_workflow(
            workflow_id,
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        queued_ids = [
            item.id
            for item in items
            if WorkflowRunStatusEnum(item.status)
            is WorkflowRunStatusEnum.QUEUED
        ]
        positions = (
            await self.workflow_run_repository.compute_queue_positions(
                queued_ids
            )
            if queued_ids
            else {}
        )
        summaries = [
            WorkflowRunSummaryDto.model_validate(item).model_copy(
                update={"queue_position": positions.get(item.id)}
            )
            for item in items
        ]
        safe_limit = max(1, limit)
        page = (offset // safe_limit) + 1
        total_pages = math.ceil(total / safe_limit) if total > 0 else 0
        return PaginationResponseDto[WorkflowRunSummaryDto](
            count=total,
            data=summaries,
            page=page,
            page_size=safe_limit,
            total_pages=total_pages,
        )

    async def get_run_details(
        self,
        workflow_id: str,
        run_id: str,
        user_id: int,
    ) -> WorkflowRunDetailDto | None:
        """Reads run details and step states strictly from PostgreSQL.

        Returns ``None`` if the run does not exist, belongs to another workflow,
        or belongs to another user. Makes no GCP API calls.
        """
        lookup_id = run_id
        if run_id.startswith("projects/") or run_id.startswith("//"):
            lookup_id = run_id.rsplit("/", maxsplit=1)[-1]

        run = await self.workflow_run_repository.get_by_id(lookup_id)
        if (
            run is None
            or run.workflow_id != workflow_id
            or run.user_id != user_id
        ):
            return None

        queue_pos: int | None = None
        if WorkflowRunStatusEnum(run.status) is WorkflowRunStatusEnum.QUEUED:
            positions = (
                await self.workflow_run_repository.compute_queue_positions(
                    [run.id]
                )
            )
            queue_pos = positions.get(run.id)

        step_entries = self._build_step_entries_from_db(run)
        detail = WorkflowRunDetailDto.model_validate(run)
        return detail.model_copy(
            update={
                "queue_position": queue_pos,
                "step_entries": step_entries,
            }
        )

    def _build_step_entries_from_db(
        self, run: WorkflowRunModel
    ) -> list[dict[str, Any]]:
        """Builds ``step_entries`` from ``step_states`` and ``workflow_snapshot``.

        Each entry carries a ``history`` array (one item per completed record
        or loop iteration); see :func:`build_step_entries`.

        When ``step_states`` is empty (e.g. a legacy row migrated before step
        checkpoints existed), returns ``[]`` without any special message.
        """
        if not run.step_states:
            return []

        snapshot = run.workflow_snapshot or {}
        try:
            workflow_model = WorkflowModel.model_validate(
                {
                    "id": snapshot.get("id") or run.workflow_id,
                    "user_id": snapshot.get("user_id") or run.user_id,
                    "name": snapshot.get("name") or "Workflow",
                    "description": snapshot.get("description"),
                    "steps": snapshot.get("steps", []),
                }
            )
        except ValidationError:
            return []

        return build_step_entries(
            workflow_model.steps,
            run.step_states,
            user_inputs=dict(run.input_args or {}),
            started_at=run.started_at,
        )

    async def resume_run(
        self,
        workflow_id: str,
        run_id: str,
        user: UserModel,
        *,
        args_override: dict[str, Any] | None = None,
    ) -> WorkflowRunModel:
        """Resumes a run against the latest workflow definition."""
        current_workflow = await self.get_workflow(user.id, workflow_id)
        return await self.run_state_service.resume(
            run_id,
            args_override=args_override,
            current_workflow=current_workflow,
            user_id=user.id,
            workflow_id=workflow_id,
        )

    async def cancel_run(
        self,
        workflow_id: str,
        run_id: str,
        user: UserModel,
    ) -> WorkflowRunModel:
        """Cancels a queued, running, or paused run."""
        return await self.run_state_service.cancel(
            run_id,
            user_id=user.id,
            workflow_id=workflow_id,
            cancel_execution_cb=self._cancel_gcp_execution,
        )

    async def _cancel_gcp_execution(
        self, run: WorkflowRunModel, execution_id: str
    ) -> None:
        """Best-effort cancellation of an in-flight GCP Workflows execution."""
        execution_client = executions_v1.ExecutionsAsyncClient()
        parent = workflows_v1.WorkflowsClient.workflow_path(
            config_service.PROJECT_ID,
            config_service.WORKFLOWS_LOCATION,
            run.workflow_id,
        )
        name = f"{parent}/executions/{execution_id}"
        await execution_client.cancel_execution(name=name)

    async def _trigger_dispatch(
        self, trigger: str, user_id: int | None
    ) -> None:
        hook = self._dispatch_hook or get_dispatch_hook()
        if hook is None:
            return
        try:
            res = hook(trigger, user_id)
            if inspect.isawaitable(res):
                await res
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Dispatch hook failed on %s.", trigger)

    async def _rollback_if_needed(self) -> None:
        """Best-effort rollback of repository DB sessions after a row failure."""
        seen_dbs: set[int] = set()
        candidate_dbs = [
            getattr(self.workflow_run_repository, "db", None),
            getattr(
                getattr(self.source_asset_service, "repo", None), "db", None
            ),
        ]
        for db in candidate_dbs:
            if db is None or id(db) in seen_dbs:
                continue
            seen_dbs.add(id(db))
            rollback_fn = getattr(db, "rollback", None)
            if not callable(rollback_fn):
                continue
            try:
                res = rollback_fn()
                if inspect.isawaitable(res):
                    await res
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Session rollback failed in WorkflowService.",
                    exc_info=True,
                )

    async def create_template(
        self,
        template_dto: WorkflowTemplateCreateDto,
        user: UserModel,
    ) -> WorkflowTemplateModel:
        """Creates a new workflow template, ensuring the name is unique per user."""
        existing = await self.workflow_template_repository.get_by_user_and_name(
            user.id, template_dto.name
        )
        if existing:
            raise ValueError(
                f"A template named '{template_dto.name}' already exists. Please choose a unique name."
            )

        template_id = f"tmpl-{uuid.uuid4()}"
        template_model = WorkflowTemplateModel(
            id=template_id,
            user_id=user.id,
            name=template_dto.name.strip(),
            description=template_dto.description,
            steps=template_dto.steps,
        )

        # Validate workflow steps structure by generating GCP workflow YAML representation.
        # This guarantees that the template is a correct working version before saving.
        self.validate_workflow(template_dto, user)

        return await self.workflow_template_repository.create(template_model)

    async def list_templates(
        self,
        user_id: int,
    ) -> list[WorkflowTemplateModel]:
        """Retrieves all templates created by the user."""
        return await self.workflow_template_repository.list_by_user(user_id)

    async def get_template(
        self,
        template_id: str,
        user_id: int,
    ) -> WorkflowTemplateModel | None:
        """Retrieves a single template if owned by the user."""
        template = await self.workflow_template_repository.get_by_id(
            template_id
        )
        if template and template.user_id == user_id:
            return template
        return None

    async def delete_template(
        self,
        template_id: str,
        user_id: int,
    ) -> bool:
        """Deletes a template if owned by the user."""
        return await self.workflow_template_repository.delete_by_id_and_user(
            template_id, user_id
        )
