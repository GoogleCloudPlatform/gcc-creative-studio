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
"""Tests for the structured executor step errors (spec §6)."""

import httpx
import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.workflows.queue.failure_classifier import ErrorCategory
from src.workflows_executor.step_errors import (
    StepError,
    StructuredErrorRoute,
    backend_error,
    invalid_input_error,
    job_failed_error,
    status_for_category,
    step_in_progress_error,
    to_step_error,
)

JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl"


@pytest.mark.parametrize(
    ("category", "original", "expected"),
    [
        (ErrorCategory.SAFETY_BLOCK, 500, 422),
        (ErrorCategory.QUOTA, None, 429),
        (ErrorCategory.STEP_IN_PROGRESS, None, 504),
        (ErrorCategory.TIMEOUT, None, 504),
        (ErrorCategory.AUTH_EXPIRED, None, 401),
        (ErrorCategory.FORBIDDEN, None, 403),
        (ErrorCategory.MISSING_RESOURCE, None, 404),
        (ErrorCategory.CAP_EXCEEDED, None, 409),
        (ErrorCategory.TRANSIENT, 502, 502),
        (ErrorCategory.TRANSIENT, 504, 504),
        (ErrorCategory.TRANSIENT, None, 503),
        (ErrorCategory.TRANSIENT, 500, 503),
        (ErrorCategory.INVALID_INPUT, 422, 422),
        (ErrorCategory.INVALID_INPUT, None, 400),
        (ErrorCategory.INVALID_INPUT, 413, 400),
        (ErrorCategory.INTERNAL, 501, 501),
        (ErrorCategory.INTERNAL, None, 500),
        (ErrorCategory.UNKNOWN, 418, 418),
        (ErrorCategory.UNKNOWN, 700, 500),
        (ErrorCategory.UNKNOWN, 200, 500),
    ],
)
def test_status_for_category(category, original, expected):
    assert status_for_category(category, original) == expected


def test_step_error_sanitises_detail_and_builds_the_body():
    error = StepError(
        500,
        ErrorCategory.INTERNAL,
        f"Backend error: Bearer {JWT}",
        headers={"Retry-After": "5"},
    )
    assert JWT not in error.detail
    assert error.to_body() == {
        "error_category": "INTERNAL",
        "detail": error.detail,
    }
    assert error.job_terminal is False
    assert error.headers == {"Retry-After": "5"}
    assert isinstance(error, HTTPException)


def test_step_error_truncates_long_details():
    error = StepError(500, ErrorCategory.INTERNAL, "x" * 10_000)
    assert len(error.detail.encode("utf-8")) <= 4096


def test_invalid_input_error():
    error = invalid_input_error("Prompt is required")
    assert error.status_code == 400
    assert error.error_category is ErrorCategory.INVALID_INPUT
    assert error.detail == "Prompt is required"


@pytest.mark.parametrize(
    ("status", "body", "expected_status", "expected_category"),
    [
        (400, "Request blocked by safety filters", 422, "SAFETY_BLOCK"),
        (500, "Responsible AI: PROHIBITED_CONTENT", 422, "SAFETY_BLOCK"),
        (429, "Quota exceeded", 429, "QUOTA"),
        (503, "Service Unavailable", 503, "TRANSIENT"),
        (502, "Bad Gateway", 502, "TRANSIENT"),
        (404, "Media item not found", 404, "MISSING_RESOURCE"),
        (401, "Token expired", 401, "AUTH_EXPIRED"),
        (403, "Forbidden", 403, "FORBIDDEN"),
        (422, '{"detail": "field required"}', 422, "INVALID_INPUT"),
        (500, "boom", 500, "INTERNAL"),
    ],
)
def test_backend_error_maps_upstream_answers(
    status, body, expected_status, expected_category
):
    error = backend_error(status, body)
    assert error.status_code == expected_status
    assert error.error_category.value == expected_category
    assert error.detail.startswith("Backend error: ")
    assert error.job_terminal is False


def test_backend_error_uses_the_prefix():
    error = backend_error(404, "gone", "Polling error")
    assert error.detail == "Polling error: gone"


@pytest.mark.parametrize(
    ("message", "expected_status", "expected_category"),
    [
        ("Image blocked by Responsible AI filters", 422, "SAFETY_BLOCK"),
        ("finish_reason=SAFETY", 422, "SAFETY_BLOCK"),
        ("RESOURCE_EXHAUSTED: quota", 429, "QUOTA"),
        ("Service unavailable", 503, "TRANSIENT"),
        ("Unknown error", 500, "UNKNOWN"),
    ],
)
def test_job_failed_error_classifies_the_job_message(
    message, expected_status, expected_category
):
    error = job_failed_error(message)
    assert error.status_code == expected_status
    assert error.error_category.value == expected_category
    assert error.detail == f"Generation job failed: {message}"
    assert error.job_terminal is True


def test_step_in_progress_error():
    error = step_in_progress_error("still running")
    assert error.status_code == 504
    assert error.error_category is ErrorCategory.STEP_IN_PROGRESS
    assert error.job_terminal is False


def test_to_step_error_keeps_step_errors():
    error = StepError(429, ErrorCategory.QUOTA, "slow down")
    assert to_step_error(error) is error


@pytest.mark.parametrize(
    ("exc", "expected_status", "expected_category"),
    [
        (HTTPException(404, "Media item not found"), 404, "MISSING_RESOURCE"),
        (HTTPException(400, "blocked by safety"), 422, "SAFETY_BLOCK"),
        (HTTPException(400, "bad request"), 400, "INVALID_INPUT"),
        (HTTPException(504, "Job still running"), 504, "TRANSIENT"),
        (HTTPException(500, "boom"), 500, "INTERNAL"),
        (HTTPException(418, "teapot"), 418, "UNKNOWN"),
    ],
)
def test_to_step_error_maps_http_exceptions(
    exc, expected_status, expected_category
):
    error = to_step_error(exc)
    assert error.status_code == expected_status
    assert error.error_category.value == expected_category
    assert error.detail == exc.detail


def test_to_step_error_keeps_http_exception_headers():
    exc = HTTPException(401, "expired", headers={"WWW-Authenticate": "Bearer"})
    assert to_step_error(exc).headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.parametrize(
    ("exc", "expected_status", "expected_category"),
    [
        (ValueError("boom"), 500, "INTERNAL"),
        (KeyError("id"), 500, "INTERNAL"),
        (httpx.ConnectError("refused"), 503, "TRANSIENT"),
        (httpx.ReadTimeout("slow"), 504, "TIMEOUT"),
        (RuntimeError("RESOURCE_EXHAUSTED"), 429, "QUOTA"),
    ],
)
def test_to_step_error_maps_unexpected_exceptions(
    exc, expected_status, expected_category
):
    error = to_step_error(exc)
    assert error.status_code == expected_status
    assert error.error_category.value == expected_category
    assert error.detail.startswith(type(exc).__name__)


def test_to_step_error_redacts_tokens_from_exception_text():
    error = to_step_error(ValueError(f"failed with Bearer {JWT}"))
    assert JWT not in error.detail


# --- StructuredErrorRoute -------------------------------------------------


class _Body(BaseModel):
    prompt: str
    count: int


def _client() -> TestClient:
    router = APIRouter(route_class=StructuredErrorRoute)

    @router.post("/ok")
    async def ok(body: _Body):
        return {"prompt": body.prompt, "count": body.count}

    @router.post("/step-error")
    async def step_error():
        raise StepError(
            422,
            ErrorCategory.SAFETY_BLOCK,
            "blocked",
            headers={"X-Step": "1"},
        )

    @router.post("/http-error")
    async def http_error():
        raise HTTPException(404, "Workflow run not found")

    @router.post("/crash")
    async def crash():
        raise RuntimeError(f"secret Bearer {JWT}")

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_route_passes_successful_responses_through():
    response = _client().post("/ok", json={"prompt": "cat", "count": 1})
    assert response.status_code == 200
    assert response.json() == {"prompt": "cat", "count": 1}


def test_route_answers_step_errors_with_the_structured_body():
    response = _client().post("/step-error")
    assert response.status_code == 422
    assert response.json() == {
        "error_category": "SAFETY_BLOCK",
        "detail": "blocked",
    }
    assert response.headers["X-Step"] == "1"


def test_route_classifies_http_exceptions():
    response = _client().post("/http-error")
    assert response.status_code == 404
    assert response.json() == {
        "error_category": "MISSING_RESOURCE",
        "detail": "Workflow run not found",
    }


def test_route_hides_unexpected_errors(caplog):
    response = _client().post("/crash")
    assert response.status_code == 500
    assert response.json() == {
        "error_category": "INTERNAL",
        "detail": "Internal error while executing the workflow step.",
    }
    assert JWT not in caplog.text


def test_route_reports_validation_errors_without_echoing_input():
    response = _client().post(
        "/ok", json={"prompt": "secret prompt", "count": "not-a-number"}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error_category"] == "INVALID_INPUT"
    assert body["detail"].startswith("Invalid request: ")
    assert "body.count" in body["detail"]
    assert "not-a-number" not in body["detail"]
    assert "secret prompt" not in body["detail"]
