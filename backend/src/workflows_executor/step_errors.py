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

"""Structured errors of the workflow executor endpoints (spec §6).

Every executor failure is answered with ``{"error_category", "detail"}`` and
an HTTP status derived from the category, so GCP Workflows (L2) and the run
state service (L3) can tell safety blocks, quota errors, still-running jobs
and our own bugs apart. Details are sanitised: no tokens, at most 4 KB.
"""

import logging
from collections.abc import Callable, Coroutine, Mapping
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.common.secret_redaction import (
    install_secret_redaction,
    sanitize_error_detail,
)
from src.workflows.queue.failure_classifier import ErrorCategory, classify

logger = install_secret_redaction(logging.getLogger(__name__))

# Categories answered with a fixed HTTP status. CAP_EXCEEDED uses 409 so
# the L2 retry predicate (429 / 5xx / network) never retries it.
_FIXED_STATUS: dict[ErrorCategory, int] = {
    ErrorCategory.SAFETY_BLOCK: 422,
    ErrorCategory.QUOTA: 429,
    ErrorCategory.STEP_IN_PROGRESS: 504,
    ErrorCategory.TIMEOUT: 504,
    ErrorCategory.AUTH_EXPIRED: 401,
    ErrorCategory.FORBIDDEN: 403,
    ErrorCategory.MISSING_RESOURCE: 404,
    ErrorCategory.CAP_EXCEEDED: 409,
}
_TRANSIENT_STATUSES = (502, 503, 504)
_INVALID_INPUT_STATUSES = (400, 422)
_MAX_VALIDATION_ERRORS = 10


def status_for_category(
    category: ErrorCategory, original_status: int | None = None
) -> int:
    """HTTP status an executor returns for ``category``.

    ``original_status`` (the upstream status, if any) is kept when it is
    consistent with the category.
    """
    fixed = _FIXED_STATUS.get(category)
    if fixed is not None:
        return fixed
    if category is ErrorCategory.TRANSIENT:
        if original_status in _TRANSIENT_STATUSES:
            return original_status
        return 503
    if category is ErrorCategory.INVALID_INPUT:
        if original_status in _INVALID_INPUT_STATUSES:
            return original_status
        return 400
    if isinstance(original_status, int) and 400 <= original_status <= 599:
        return original_status
    return 500


class StepError(HTTPException):
    """HTTP error of a workflow step, tagged with its failure category.

    Attributes:
        error_category: The failure category (also read by the classifier).
        job_terminal: The generation job itself ended (failed or exceeded
            the step duration cap); later calls must not keep reusing it.
        retry_safe: Whether repeating the call cannot start a duplicate
            generation job. ``False`` (sent as ``"retry_safe": false``)
            stops the L2 retries of the generated YAML (spec §7.1).
    """

    def __init__(
        self,
        status_code: int,
        category: ErrorCategory,
        detail: Any,
        *,
        job_terminal: bool = False,
        retry_safe: bool = True,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail=sanitize_error_detail(detail),
            headers=dict(headers) if headers else None,
        )
        self.error_category = category
        self.job_terminal = job_terminal
        self.retry_safe = retry_safe

    def to_body(self) -> dict[str, Any]:
        """Structured response body (``retry_safe`` only when false)."""
        body: dict[str, Any] = {
            "error_category": self.error_category.value,
            "detail": self.detail,
        }
        if not self.retry_safe:
            body["retry_safe"] = False
        return body


def invalid_input_error(detail: str) -> StepError:
    """400 ``INVALID_INPUT`` error for a request the step cannot run."""
    return StepError(400, ErrorCategory.INVALID_INPUT, detail)


def backend_error(
    status_code: int, body_text: str, prefix: str = "Backend error"
) -> StepError:
    """Maps a non-200 answer of a backend endpoint to a :class:`StepError`.

    Safety blocks reported as 400 / 500 become 422 ``SAFETY_BLOCK``.
    """
    classification = classify({"http_status": status_code, "body": body_text})
    return StepError(
        status_for_category(classification.category, status_code),
        classification.category,
        f"{prefix}: {body_text}",
    )


def job_failed_error(error_message: str) -> StepError:
    """Error for a generation job whose gallery item ended ``failed``."""
    classification = classify({"error_message": error_message})
    return StepError(
        status_for_category(classification.category),
        classification.category,
        f"Generation job failed: {error_message}",
        job_terminal=True,
    )


def step_in_progress_error(detail: str) -> StepError:
    """504 ``STEP_IN_PROGRESS``: the job is still running; retry to resume."""
    return StepError(504, ErrorCategory.STEP_IN_PROGRESS, detail)


def to_step_error(error: BaseException) -> StepError:
    """Converts any exception raised by a step into a :class:`StepError`.

    Unexpected exceptions without any recognisable signal are our own
    ``INTERNAL`` errors.
    """
    if isinstance(error, StepError):
        return error
    if isinstance(error, StarletteHTTPException):
        classification = classify(error)
        return StepError(
            status_for_category(classification.category, error.status_code),
            classification.category,
            error.detail,
            headers=error.headers,
        )
    classification = classify(error)
    category = classification.category
    if category is ErrorCategory.UNKNOWN:
        category = ErrorCategory.INTERNAL
    return StepError(
        status_for_category(category),
        category,
        f"{type(error).__name__}: {error}",
    )


def _validation_detail(error: RequestValidationError) -> str:
    """Location and message of each validation error, never the input."""
    parts = []
    for item in error.errors()[:_MAX_VALIDATION_ERRORS]:
        location = ".".join(str(part) for part in item.get("loc", ()))
        message = item.get("msg", "invalid value")
        parts.append(f"{location}: {message}")
    return "Invalid request: " + "; ".join(parts)


class StructuredErrorRoute(APIRoute):
    """Route class answering every error with a structured step error."""

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except RequestValidationError as exc:
                error = StepError(
                    422, ErrorCategory.INVALID_INPUT, _validation_detail(exc)
                )
            except StarletteHTTPException as exc:
                error = to_step_error(exc)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Unhandled error in a workflow step.")
                error = StepError(
                    500,
                    ErrorCategory.INTERNAL,
                    "Internal error while executing the workflow step.",
                )
            return JSONResponse(
                status_code=error.status_code,
                content=error.to_body(),
                headers=error.headers,
            )

        return handler
