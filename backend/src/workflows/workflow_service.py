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

from fastapi import Depends
import logging
import uuid
import json

import yaml
from google.cloud import workflows_v1
from google.cloud.workflows import executions_v1
from google.api_core.exceptions import NotFound
from google.auth.transport.requests import Request
from google.oauth2 import service_account
import google.auth
import requests
from pydantic import BaseModel, ValidationError

from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.config.config_service import config_service
from src.images.imagen_service import ImagenService
from src.users.user_model import UserModel
from src.workflows.dto.workflow_search_dto import WorkflowSearchDto
from src.workflows.repository.workflow_repository import WorkflowRepository
from google.auth.transport.requests import AuthorizedSession
from src.workflows.schema.workflow_model import (
    NodeTypes,
    WorkflowCreateDto,
    StepOutputReference,
    WorkflowModel,
)

logger = logging.getLogger(__name__)
PROJECT_ID = config_service.PROJECT_ID
LOCATION = config_service.WORKFLOWS_LOCATION
BACKEND_EXECUTOR_URL = config_service.WORKFLOWS_EXECUTOR_URL


class WorkflowService:
    """Orchestrates multi-step generative AI workflows."""

    def __init__(self, workflow_repository: WorkflowRepository = Depends()):
        self.imagen_service = ImagenService()
        self.workflow_repository = workflow_repository

    def _generate_workflow_yaml(
        self,
        workflow: WorkflowModel,
    ):
        """
        This function contains the business logic for generating the workflow.
        """
        user_id = workflow.user_id
        logger.info(
            f"Received workflow generation request for user {user_id}"
        )
        # A very basic transformation to a GCP-like workflow structure
        step_outputs = {}
        gcp_steps = []
        # We init with this default param that is going to propagate user auth header
        workflow_params = ["user_auth_header"]
        user_input_step_id = None

        for step in workflow.steps:
            if step.type.value == NodeTypes.USER_INPUT:
                print("USER INPUT FOUND")
                # This is a user input step, so we should treat it as a workflow parameter
                user_input_step_id = step.step_id
                for output_name, output_value in step.outputs.items():
                    workflow_params.append(output_name)
                continue

            step_type = step.type.value.lower()
            step_name = step.step_id
            config = step.settings if step.settings else {}
            config = (
                config.model_dump() if isinstance(config, BaseModel) else config
            )

            # Resolve inputs
            resolved_inputs = {}

            def resolve_value(value):
                # If it's a StepOutputReference (dict with step and output)
                if isinstance(value, dict) and "step" in value and "output" in value:
                    ref_step_id = value["step"]
                    ref_output_name = value["output"]

                    if ref_step_id == user_input_step_id:
                        return f"${{args.{ref_output_name}}}"
                    else:
                        return f"${{{ref_step_id}_result.body.{ref_output_name}}}"
                # If it's a list, resolve each item
                elif isinstance(value, list):
                    return [resolve_value(item) for item in value]
                # Otherwise, return as is
                else:
                    return value

            for input_name, input_value in step.inputs.model_dump().items():
                resolved_inputs[input_name] = resolve_value(input_value)

            body = {
                "workspace_id": "${args.workspace_id}",  # Dynamically injected from workspaceId passed at execution
                "inputs": resolved_inputs,
                "config": config,
            }

            gcp_step = {
                step_name: {
                    "call": "http.post",
                    "args": {
                        "url": f"{BACKEND_EXECUTOR_URL}/{step_type}",
                        "headers": {
                            "Authorization": "${args.user_auth_header}"
                        },
                        "body": body,
                    },
                    "result": f"{step_name}_result",
                }
            }
            gcp_steps.append(gcp_step)

            # Store mock outputs for subsequent steps
            step_outputs[step_name] = {
                output_name: f"{step_name}_result.{output_name}"
                for output_name in step.outputs
            }

        gcp_workflow = {"main": {"params": ["args"], "steps": gcp_steps}}

        yaml_output = yaml.dump(gcp_workflow, indent=2)

        return yaml_output

    def _create_gcp_workflow(self, source_contents: str, workflow_id: str):
        client = workflows_v1.WorkflowsClient()

        # Initialize request argument(s)
        workflow = workflows_v1.Workflow()
        workflow.source_contents = source_contents
        workflow.execution_history_level = (
            workflows_v1.ExecutionHistoryLevel.EXECUTION_HISTORY_DETAILED
        )
        if config_service.BACKEND_SERVICE_ACCOUNT_EMAIL:
            workflow.service_account = config_service.BACKEND_SERVICE_ACCOUNT_EMAIL

        request = workflows_v1.CreateWorkflowRequest(
            parent=f"projects/{PROJECT_ID}/locations/{LOCATION}",
            workflow=workflow,
            workflow_id=workflow_id,
        )

        operation = client.create_workflow(request=request)
        response = operation.result()
        return response

    def _update_gcp_workflow(self, source_contents: str, workflow_id: str):
        client = workflows_v1.WorkflowsClient()

        # Initialize request argument(s)
        workflow = workflows_v1.Workflow(name = f"projects/{PROJECT_ID}/locations/{LOCATION}/workflows/{workflow_id}")
        workflow.source_contents = source_contents
        workflow.execution_history_level = (
            workflows_v1.ExecutionHistoryLevel.EXECUTION_HISTORY_DETAILED
        )
        if config_service.BACKEND_SERVICE_ACCOUNT_EMAIL:
            workflow.service_account = config_service.BACKEND_SERVICE_ACCOUNT_EMAIL

        request = workflows_v1.UpdateWorkflowRequest(
            workflow=workflow,
        )

        operation = client.update_workflow(request=request)
        response = operation.result()
        return response

    def _delete_gcp_workflow(self, workflow_id: str):
        client = workflows_v1.WorkflowsClient()

        # Construct the fully qualified location path.
        parent = client.workflow_path(
            config_service.PROJECT_ID, config_service.WORKFLOWS_LOCATION, workflow_id
        )

        request = workflows_v1.DeleteWorkflowRequest(
            name=parent,
        )

        try:
            operation = client.delete_workflow(request=request)
            response = operation.result()
            logger.info(f"Deleted GCP workflow for id '{workflow_id}' with response '{response}'")
            return response
        except NotFound:
            logger.warning(f"Workflow '{workflow_id}' not found in GCP. Proceeding with local deletion.")
            return None

    async def create_workflow(
        self, workflow_dto: WorkflowCreateDto, user: UserModel
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
            created_workflow = await self.workflow_repository.create(workflow_model)

            # 3. Generate GCP Workflow YAML (using the same ID)
            yaml_output = self._generate_workflow_yaml(created_workflow)
            logger.info("Generated YAML:")
            logger.info(yaml_output)

            # 4. Create GCP Workflow
            try:
                self._create_gcp_workflow(yaml_output, workflow_id)
            except Exception as e:
                # Rollback DB creation if GCP creation fails
                logger.error(f"Failed to create GCP workflow: {e}. Rolling back DB.")
                await self.workflow_repository.delete(created_workflow.id)
                raise e

            return created_workflow
        except ValidationError as e:
            raise ValueError(str(e))
        except Exception as e:
            # TODO: Improve error handling here
            logging.error(e)
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
        self, user_id: int, search_dto: WorkflowSearchDto
    ) -> PaginationResponseDto[WorkflowModel]:
        return await self.workflow_repository.query(user_id, search_dto)

    async def update_workflow(
        self, workflow_id: str, workflow_dto: WorkflowCreateDto, user: UserModel
    ) -> WorkflowModel | None:
        """Validates and updates a workflow."""
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

            return await self.workflow_repository.update(workflow_id, updated_model)
        except ValidationError as e:
            raise ValueError(str(e))

    async def delete_by_id(self, workflow_id: str) -> bool:
        """Deletes a workflow from the system."""
        # The GCP workflow ID matches the DB ID
        self._delete_gcp_workflow(workflow_id)
        response = await self.workflow_repository.delete(workflow_id)
        return response

    def execute_workflow(self, workflow_id: str, args: dict) -> str:
        """Executes a workflow."""

        # Initialize API clients.
        execution_client = executions_v1.ExecutionsClient()
        workflows_client = workflows_v1.WorkflowsClient()

        # Construct the fully qualified location path.
        # Ensure we use the correct ID (it assumes workflow_id is already the full ID string)
        parent = workflows_client.workflow_path(
            config_service.PROJECT_ID, config_service.WORKFLOWS_LOCATION, workflow_id
        )

        execution = executions_v1.Execution(argument=json.dumps(args))

        # Execute the workflow.
        response = execution_client.create_execution(
            parent=parent, execution=execution
        )

        # Extract just the execution ID (UUID) from the full resource name
        # Format: projects/{project}/locations/{location}/workflows/{workflow}/executions/{execution_id}
        execution_id = response.name.split('/')[-1]
        return execution_id

    async def get_execution_details(
        self, workflow_id: str, execution_id: str
    ) -> dict | None:
        """Retrieves the details of a workflow execution."""
        client = executions_v1.ExecutionsClient()

        if not execution_id.startswith("projects/"):
            parent = client.workflow_path(
                config_service.PROJECT_ID,
                config_service.WORKFLOWS_LOCATION,
                workflow_id,
            )
            execution_name = f"{parent}/executions/{execution_id}"
        else:
            execution_name = execution_id

        try:
            execution = client.get_execution(name=execution_name)
        except NotFound:
            return None

        result = None
        user_inputs = json.loads(execution.argument) if execution.argument else {}
        if execution.state == executions_v1.Execution.State.SUCCEEDED:
            result = execution.result

        # Fetch step entries using REST API
        try:
            credentials, project = google.auth.default(
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
            authed_session = AuthorizedSession(credentials)
            url = f"https://workflowexecutions.googleapis.com/v1/{execution_name}/stepEntries"
            response = authed_session.get(url)
            if response.status_code == 200:
                step_entries = response.json().get("stepEntries", [])
            else:
                logger.warning(f"Failed to fetch step entries: {response.text}")
                step_entries = [] # Ensure step_entries is defined
        except Exception as e:
            logger.error(f"Error fetching step entries: {e}")
            step_entries = []

        # Calculate duration
        duration = 0.0
        if execution.start_time:
            start_timestamp = execution.start_time.timestamp()  # type: ignore
            if execution.end_time:
                end_timestamp = execution.end_time.timestamp()  # type: ignore
                duration = end_timestamp - start_timestamp
            else:
                import time
                duration = time.time() - start_timestamp

        # Fetch workflow definition for input resolution
        workflow_model = await self.get_by_id(workflow_id)
        if not workflow_model:
            # If workflow definition is missing, we might still return basic execution details
            logger.warning(f"Workflow definition {workflow_id} not found for execution {execution_id}")
            return {
                "id": execution.name,
                "state": execution.state.name,
                "result": result,
                "duration": round(duration, 2),
                "error": execution.error.context if execution.error else None,
                "step_entries": [] # Cannot map steps without definition
            }

        user_input_step_id = workflow_model.steps[0].step_id

        previous_outputs = {}
        formatted_step_entries = []

        # 1. Add User Input Step Entry (Virtual)
        # This ensures the User Input step appears in the history and its outputs are available for resolution
        previous_outputs[user_input_step_id] = user_inputs
        formatted_step_entries.append(
            {
                "step_id": user_input_step_id,
                "state": "STATE_SUCCEEDED",  # User input is always considered succeeded if execution started
                "step_inputs": {},
                "step_outputs": user_inputs,
                "start_time": execution.start_time.isoformat() if execution.start_time else None,  # type: ignore
                "end_time": (
                    execution.start_time.isoformat()  # type: ignore
                    if execution.start_time
                    else None
                ),  # Instant # type: ignore
            }
        )

        def resolve_value(value):
            if isinstance(value, StepOutputReference):
                return previous_outputs.get(value.step, {}).get(value.output)
            elif isinstance(value, list):
                return [resolve_value(item) for item in value]
            else:
                return value

        for entry in step_entries:
            step_id = entry.get("step")
            if step_id == "end":
                continue

            # Find the step definition
            current_step = next((step for step in workflow_model.steps if step.step_id == step_id), None)
            if not current_step:
                continue

            step_state = entry.get("state")

            # Extract inputs from step
            step_inputs = {}
            for inp_name, inp_value in current_step.inputs:
                step_inputs[inp_name] = resolve_value(inp_value)

            # Extract outputs from step
            variable_data = entry.get("variableData", {})
            variables = variable_data.get("variables", {})
            step_results = variables.get(f"{step_id}_result", {})
            step_outputs = step_results.get("body", {})

            # Store outputs for subsequent steps
            previous_outputs[step_id] = step_outputs

            formatted_step_entries.append({
                "step_id": step_id,
                "state": step_state,
                "step_inputs": step_inputs,
                "step_outputs": step_outputs,
                "start_time": entry.get("createTime"),
                "end_time": entry.get("updateTime")
            })

        return {
            "id": execution.name,
            "state": execution.state.name,
            "result": result,
            "duration": round(duration, 2),
            "error": execution.error.context if execution.error else None,
            "step_entries": formatted_step_entries
        }

    def list_executions(
        self,
        workflow_id: str,
        limit: int = 10,
        page_token: str | None = None,
        filter_str: str | None = None,
    ):
        """Lists executions for a given workflow."""
        client = executions_v1.ExecutionsClient()
        parent = client.workflow_path(PROJECT_ID, LOCATION, workflow_id)

        request = executions_v1.ListExecutionsRequest(
            parent=parent,
            page_size=limit,
            page_token=page_token,
            filter=filter_str
        )

        response = client.list_executions(request=request)
        pages_iterator = response.pages

        try:
            current_page = next(pages_iterator)
        except StopIteration:
            print("No executions found.")
            return None

        executions = []
        for execution in current_page.executions:
            # Calculate duration
            duration = 0.0
            if execution.start_time:
                start_timestamp = execution.start_time.timestamp()  # type: ignore
                if execution.end_time:
                    end_timestamp = execution.end_time.timestamp()  # type: ignore
                    duration = end_timestamp - start_timestamp
                else:
                    import time
                    duration = time.time() - start_timestamp

            executions.append(
                {
                    "id": execution.name.split("/")[-1],
                    "state": execution.state.name,
                    "start_time": execution.start_time,
                    "end_time": execution.end_time,
                    "duration": round(duration, 2),
                    "error": execution.error.context if execution.error else None,
                }
            )

        return {
            "executions": executions,
            "next_page_token": current_page.next_page_token,
        }
