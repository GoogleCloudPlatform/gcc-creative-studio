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
"""Utility functions for workflows."""

import re
from typing import Any


def interpolate_prompt_variables(
    prompt: str,
    variables: dict[str, Any] | None = None,
    keep_unresolved: bool = False,
) -> str:
    """Interpolates <var_name> placeholders in prompt using provided variables.

    Args:
        prompt: The prompt template containing <var_name> placeholders.
        variables: Dictionary mapping variable names to their values.
        keep_unresolved: If True, placeholders with missing or None values
            remain unchanged (e.g. '<var_name>'). If False, placeholders with
            missing or None values are replaced with an empty string.

    Returns:
        The interpolated prompt string.
    """
    if not prompt:
        return prompt or ""

    vars_dict = variables or {}
    vars_lower = {str(k).lower(): v for k, v in vars_dict.items()}

    def replace_var(match: re.Match) -> str:
        var_name = match.group(1)
        val = vars_lower.get(var_name.lower())
        if val is None:
            return match.group(0) if keep_unresolved else ""
        if isinstance(val, dict):
            return str(val.get("generated_text") or val.get("text") or "")
        return str(val)

    return re.sub(r"<([a-zA-Z0-9_]+)>", replace_var, prompt)
