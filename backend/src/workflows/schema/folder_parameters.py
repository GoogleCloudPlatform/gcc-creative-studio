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

"""Helpers for workflow Folder-type user input parameters."""

from collections.abc import Iterable, Mapping
from typing import Any

from src.workflows.schema.workflow_model import NodeTypes

FOLDER_PARAMETER_TYPE = "folder"


def folder_arg_names(steps: Iterable[Any]) -> frozenset[str]:
    """Execution argument names of the Folder parameters in ``steps``."""
    return frozenset(
        name
        for step in steps
        if step.type == NodeTypes.USER_INPUT
        for name, output in (step.outputs or {}).items()
        if isinstance(output, Mapping)
        and output.get("type") == FOLDER_PARAMETER_TYPE
    )
