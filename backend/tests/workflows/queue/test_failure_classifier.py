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
"""Tests for the workflow step failure classifier (spec §6)."""

import dataclasses
import json

import httpx
import pytest
from fastapi import HTTPException
from google.api_core import exceptions as core_exceptions
from google.auth import exceptions as auth_exceptions
from google.genai import errors as genai_errors

from src.workflows.queue.failure_classifier import (
    Classification,
    ErrorCategory,
    classify,
    counts_as_attempt,
    is_transient_or_quota,
)


def _gcp_http_error(code: int, body=None) -> dict:
    """Shape of ``e`` in a GCP Workflows ``except`` block for HTTP errors."""
    return {
        "message": f"HTTP server responded with error code {code}",
        "code": code,
        "tags": ["HttpError"],
        "headers": {"Content-Type": "application/json"},
        "body": body,
    }


def _genai_error(cls, code: int, message: str, status: str):
    return cls(
        code, {"error": {"code": code, "message": message, "status": status}}
    )


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://backend/api/images")
    return httpx.HTTPStatusError(
        "boom",
        request=request,
        response=httpx.Response(status_code, request=request),
    )


class _ExplodingError(Exception):
    """Exception whose attributes and string conversion all fail."""

    @property
    def status_code(self):
        raise RuntimeError("no status")

    @property
    def detail(self):
        raise RuntimeError("no detail")

    def __str__(self):
        raise RuntimeError("no str")


class _Opaque:
    """Arbitrary object that only has a string representation."""

    def __str__(self):
        return "opaque value"


# --- TRANSIENT ------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        502,
        503,
        504,
        _gcp_http_error(503),
        {"tags": ["ConnectionError"], "message": "connection reset"},
        {"tags": ["ConnectionFailedError"]},
        httpx.ConnectError("connection refused"),
        httpx.ConnectTimeout("connect timeout"),
        httpx.RemoteProtocolError("server disconnected"),
        ConnectionResetError("reset by peer"),
        auth_exceptions.TransportError("dns failure"),
        core_exceptions.ServiceUnavailable("backend unavailable"),
        _genai_error(
            genai_errors.ServerError, 503, "The model is overloaded.", "X"
        ),
        _http_status_error(502),
        "Service temporarily unavailable, please retry",
    ],
)
def test_transient_errors_are_retryable_attempts(error):
    result = classify(error)
    assert result.category is ErrorCategory.TRANSIENT
    assert result.retryable is True
    assert result.counts_as_attempt is True


def test_plain_504_without_inflight_job_is_transient():
    assert classify(504).category is ErrorCategory.TRANSIENT


# --- QUOTA ----------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        429,
        "RESOURCE_EXHAUSTED",
        "Quota exceeded for aiplatform.googleapis.com/generate_requests",
        "429 Too Many Requests",
        _gcp_http_error(429, {"error": {"message": "Rate limit reached"}}),
        _genai_error(
            genai_errors.ClientError,
            429,
            "Resource has been exhausted (e.g. check quota).",
            "RESOURCE_EXHAUSTED",
        ),
        core_exceptions.ResourceExhausted("quota"),
        {"http_status": 500, "body": "RESOURCE_EXHAUSTED: try later"},
        {"error_category": "quota"},
    ],
)
def test_quota_errors_are_retryable(error):
    result = classify(error)
    assert result.category is ErrorCategory.QUOTA
    assert result.retryable is True
    assert result.counts_as_attempt is True


# --- STEP_IN_PROGRESS -----------------------------------------------------


@pytest.mark.parametrize(
    ("error", "has_inflight_job"),
    [
        ({"error_category": "STEP_IN_PROGRESS", "detail": "running"}, False),
        (
            _gcp_http_error(
                504,
                {"error_category": "STEP_IN_PROGRESS", "detail": "running"},
            ),
            False,
        ),
        (
            _gcp_http_error(
                504, json.dumps({"error_category": "STEP_IN_PROGRESS"})
            ),
            False,
        ),
        ({"tags": ["TimeoutError"], "message": "timed out"}, True),
        (_gcp_http_error(504), True),
        ({"error_category": "TIMEOUT"}, True),
        (TimeoutError("read timed out"), True),
    ],
)
def test_step_in_progress_never_consumes_attempts(error, has_inflight_job):
    result = classify(
        error, has_inflight_job=has_inflight_job, attempt=99, max_attempts=5
    )
    assert result.category is ErrorCategory.STEP_IN_PROGRESS
    assert result.retryable is True
    assert result.counts_as_attempt is False


# --- TIMEOUT --------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        {"tags": ["TimeoutError"], "message": "timed out"},
        TimeoutError("timed out"),
        httpx.ReadTimeout("read timeout"),
        {"error_category": "TIMEOUT"},
    ],
)
def test_timeout_without_inflight_job_counts_as_attempt(error):
    result = classify(error)
    assert result.category is ErrorCategory.TIMEOUT
    assert result.retryable is True
    assert result.counts_as_attempt is True


def test_timeout_stops_being_retryable_at_the_attempt_cap():
    result = classify({"tags": ["TimeoutError"]}, attempt=5, max_attempts=5)
    assert result.category is ErrorCategory.TIMEOUT
    assert result.retryable is False
    assert "attempt cap reached (5/5)" in result.reason


# --- Auth -----------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        401,
        _gcp_http_error(401, "Token expired"),
        HTTPException(status_code=401, detail="Invalid token"),
        # The auth status wins over any other keyword in the body.
        {"http_status": 401, "body": "request blocked"},
    ],
)
def test_401_waits_for_a_session_without_consuming_attempts(error):
    result = classify(error, attempt=10, max_attempts=5)
    assert result.category is ErrorCategory.AUTH_EXPIRED
    assert result.retryable is True
    assert result.counts_as_attempt is False


@pytest.mark.parametrize(
    "error",
    [403, HTTPException(status_code=403, detail="Forbidden")],
)
def test_403_needs_attention(error):
    result = classify(error)
    assert result.category is ErrorCategory.FORBIDDEN
    assert result.retryable is False


# --- Terminal categories --------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        400,
        422,
        HTTPException(status_code=400, detail="bad aspect ratio"),
        _gcp_http_error(422, {"detail": "field required"}),
    ],
)
def test_invalid_input_is_not_retryable(error):
    result = classify(error)
    assert result.category is ErrorCategory.INVALID_INPUT
    assert result.retryable is False
    assert result.counts_as_attempt is True


@pytest.mark.parametrize(
    "error",
    [
        "Image generation failed: blocked by Responsible AI filters",
        {
            "error_message": (
                "The prompt could not be submitted. This prompt contains "
                "sensitive words that violate Google's Responsible AI "
                "practices."
            )
        },
        {"http_status": 500, "body": "PROHIBITED_CONTENT"},
        {"http_status": 400, "body": {"detail": "finish_reason=SAFETY"}},
        {"http_status": 429, "body": "raiMediaFilteredReasons: [...]"},
        {"error_category": "SAFETY_BLOCK", "detail": "blocked"},
        {"error_category": "INTERNAL", "detail": "blocked by safety"},
        _genai_error(
            genai_errors.ClientError,
            400,
            "Request blocked by safety filters",
            "INVALID_ARGUMENT",
        ),
        _gcp_http_error(
            422,
            {"error_category": "SAFETY_BLOCK", "detail": "RAI filtered"},
        ),
    ],
)
def test_safety_blocks_are_never_retryable(error):
    result = classify(error, attempt=1, max_attempts=5)
    assert result.category is ErrorCategory.SAFETY_BLOCK
    assert result.retryable is False


@pytest.mark.parametrize(
    "error",
    [
        404,
        HTTPException(status_code=404, detail="Media item not found"),
        _gcp_http_error(404),
        '{"code": 404}',
        {"error_category": "NOT_A_CATEGORY", "code": 404},
    ],
)
def test_missing_resources_need_attention(error):
    result = classify(error)
    assert result.category is ErrorCategory.MISSING_RESOURCE
    assert result.retryable is False


def test_cap_exceeded_is_terminal_and_not_an_attempt():
    for error in (
        ErrorCategory.CAP_EXCEEDED,
        {"errorCategory": "CAP_EXCEEDED"},
    ):
        result = classify(error)
        assert result.category is ErrorCategory.CAP_EXCEEDED
        assert result.retryable is False
        assert result.counts_as_attempt is False


# --- INTERNAL / UNKNOWN ---------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        500,
        501,
        _gcp_http_error(500, {"error_category": "INTERNAL", "detail": "x"}),
        {"category": "INTERNAL"},
        _http_status_error(500),
    ],
)
def test_internal_errors_are_retryable_until_the_cap(error):
    first = classify(error, attempt=1, max_attempts=5)
    assert first.category is ErrorCategory.INTERNAL
    assert first.retryable is True
    assert classify(error, attempt=4, max_attempts=5).retryable is True
    last = classify(error, attempt=5, max_attempts=5)
    assert last.retryable is False
    assert "attempt cap reached (5/5)" in last.reason


def test_internal_errors_without_a_cap_stay_retryable():
    assert classify(500, attempt=50).retryable is True


@pytest.mark.parametrize(
    "error",
    [
        None,
        True,
        418,
        [],
        {"foo": "bar"},
        ValueError("weird"),
        _Opaque(),
        "{not json",
        {"error_category": "UNKNOWN"},
    ],
)
def test_garbage_is_unknown_and_retried_once(error):
    first = classify(error)
    assert first.category is ErrorCategory.UNKNOWN
    assert first.retryable is True
    second = classify(error, attempt=2, max_attempts=5)
    assert second.retryable is False
    assert "(2/2)" in second.reason


def test_unknown_respects_a_lower_attempt_cap():
    result = classify(ValueError("weird"), attempt=1, max_attempts=1)
    assert result.retryable is False


# --- Signal extraction ----------------------------------------------------


def test_hint_from_exception_attribute_wins():
    error = HTTPException(status_code=500, detail="boom")
    error.error_category = "QUOTA"
    assert classify(error).category is ErrorCategory.QUOTA


def test_hint_from_http_exception_detail_mapping():
    error = HTTPException(
        status_code=504, detail={"error_category": "STEP_IN_PROGRESS"}
    )
    assert classify(error).category is ErrorCategory.STEP_IN_PROGRESS


def test_bytes_payload_is_decoded():
    payload = b'{"error_category": "QUOTA", "detail": "slow down"}'
    assert classify(payload).category is ErrorCategory.QUOTA


def test_cause_chain_is_followed():
    try:
        try:
            raise httpx.ConnectError("refused")
        except httpx.ConnectError as inner:
            raise RuntimeError("wrapper") from inner
    except RuntimeError as outer:
        assert classify(outer).category is ErrorCategory.TRANSIENT


def test_outermost_status_wins():
    error = {"code": 404, "body": {"code": 503}}
    assert classify(error).category is ErrorCategory.MISSING_RESOURCE


def test_grpc_style_status_text_is_read():
    error = _genai_error(
        genai_errors.ClientError, 0, "exhausted", "RESOURCE_EXHAUSTED"
    )
    error.code = None
    assert classify(error).category is ErrorCategory.QUOTA


def test_numeric_status_attribute_is_read():
    error = Exception("x")
    error.status = 404
    assert classify(error).category is ErrorCategory.MISSING_RESOURCE


def test_exploding_attributes_do_not_break_classification():
    result = classify(_ExplodingError())
    assert result.category is ErrorCategory.UNKNOWN


def test_deeply_nested_payload_is_bounded():
    payload: dict = {"message": "RESOURCE_EXHAUSTED"}
    for _ in range(20):
        payload = {"error": payload}
    assert classify(payload).category is ErrorCategory.UNKNOWN


def test_long_lists_are_bounded():
    payload = [{"foo": "bar"}] * 50 + [429]
    assert classify(payload).category is ErrorCategory.UNKNOWN


def test_booleans_are_not_statuses():
    assert classify({"code": True, "status": 404}).category is (
        ErrorCategory.MISSING_RESOURCE
    )


def test_reason_never_echoes_raw_error_text():
    secret = "Bearer abc.def.ghi"
    result = classify({"http_status": 500, "detail": secret})
    assert secret not in result.reason


def test_classification_is_immutable():
    result = classify(500)
    assert isinstance(result, Classification)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.retryable = False  # type: ignore[misc]


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        (ErrorCategory.TRANSIENT, True),
        (ErrorCategory.QUOTA, True),
        (ErrorCategory.TIMEOUT, True),
        (ErrorCategory.INTERNAL, True),
        (ErrorCategory.UNKNOWN, True),
        (ErrorCategory.SAFETY_BLOCK, True),
        (ErrorCategory.STEP_IN_PROGRESS, False),
        (ErrorCategory.AUTH_EXPIRED, False),
        (ErrorCategory.CAP_EXCEEDED, False),
    ],
)
def test_counts_as_attempt(category, expected):
    assert counts_as_attempt(category) is expected


# --- L1 predicate ---------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        429,
        503,
        "RESOURCE_EXHAUSTED",
        httpx.ConnectError("refused"),
        httpx.ConnectTimeout("connect timeout"),
        httpx.RemoteProtocolError("disconnected"),
        ConnectionError("reset"),
        auth_exceptions.TransportError("dns"),
        core_exceptions.ServiceUnavailable("down"),
        core_exceptions.ResourceExhausted("quota"),
        _genai_error(genai_errors.ClientError, 429, "exhausted", "X"),
        _genai_error(genai_errors.ServerError, 503, "overloaded", "X"),
        {"tags": ["ConnectionError"]},
        "Service temporarily unavailable",
    ],
)
def test_l1_predicate_retries_quota_503_and_network(error):
    assert is_transient_or_quota(error) is True


@pytest.mark.parametrize(
    "error",
    [
        400,
        401,
        403,
        404,
        422,
        500,
        502,
        504,
        "blocked by Responsible AI filters",
        {"http_status": 429, "body": "blocked by safety filters"},
        _genai_error(genai_errors.ClientError, 400, "blocked by safety", "X"),
        _genai_error(genai_errors.ServerError, 500, "internal", "X"),
        core_exceptions.InternalServerError("boom"),
        core_exceptions.DeadlineExceeded("deadline"),
        ValueError("bug"),
        httpx.ReadTimeout("read timeout"),
        TimeoutError("timeout"),
        {"error_category": "STEP_IN_PROGRESS"},
        HTTPException(status_code=400, detail="bad request"),
    ],
)
def test_l1_predicate_never_retries_other_errors(error):
    assert is_transient_or_quota(error) is False
