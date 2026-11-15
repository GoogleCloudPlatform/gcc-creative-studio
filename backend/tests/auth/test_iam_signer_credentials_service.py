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
"""Tests for IamSignerCredentials lazy clients, caching, and async signing."""

import asyncio
import datetime
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from src.auth import iam_signer_credentials_service as signer_mod
from src.auth.iam_signer_credentials_service import (
    DEFAULT_PRESIGNED_EXPIRATION_HOURS,
    IamSignerCredentials,
    clear_signer_cache,
)


@pytest.fixture(autouse=True)
def _reset_signer_state(monkeypatch):
    clear_signer_cache()
    monkeypatch.setenv(
        "SIGNING_SA_EMAIL", "signer@example.iam.gserviceaccount.com"
    )
    yield
    clear_signer_cache()


def test_lazy_client_init_and_singleton_reuse():
    with (
        patch.object(
            signer_mod.iam_credentials_v1, "IAMCredentialsClient"
        ) as iam_cls,
        patch.object(signer_mod.storage, "Client") as storage_cls,
    ):
        signer_a = IamSignerCredentials()
        signer_b = IamSignerCredentials()

        # __init__ must not trigger cloud clients or ADC lookups.
        iam_cls.assert_not_called()
        storage_cls.assert_not_called()

        # Non-GCS URI must not trigger cloud clients.
        assert signer_a.generate_presigned_url("https://example.com/a.png") == (
            "https://example.com/a.png"
        )
        assert signer_a.generate_presigned_url("") == ""
        storage_cls.assert_not_called()
        iam_cls.assert_not_called()

        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = "https://signed/1"
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        storage_cls.return_value.bucket.return_value = mock_bucket

        url1 = signer_a.generate_presigned_url("gs://my-bucket/obj1.png")
        url2 = signer_b.generate_presigned_url("gs://my-bucket/obj2.png")

        assert url1 == "https://signed/1"
        assert url2 == "https://signed/1"
        # Shared storage client initialized only once across distinct instances.
        storage_cls.assert_called_once()
        # Accessing iam_client initializes IAM singleton once across instances.
        _ = signer_a.iam_client
        _ = signer_b.iam_client
        iam_cls.assert_called_once()


def test_missing_signing_email_skips_clients(monkeypatch):
    monkeypatch.setenv("SIGNING_SA_EMAIL", "")
    with patch.object(signer_mod.storage, "Client") as storage_cls:
        signer = IamSignerCredentials()
        assert signer.generate_presigned_url("gs://bucket/a.png") == (
            "gs://bucket/a.png"
        )
        storage_cls.assert_not_called()


def test_six_hour_ttl_and_refresh_buffer():
    with patch.object(signer_mod.storage, "Client") as storage_cls:
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.side_effect = [
            "https://signed/first",
            "https://signed/refreshed",
        ]
        storage_cls.return_value.bucket.return_value.blob.return_value = (
            mock_blob
        )

        signer = IamSignerCredentials()
        url1 = signer.generate_presigned_url("gs://bucket/a.webp")
        assert url1 == "https://signed/first"
        assert DEFAULT_PRESIGNED_EXPIRATION_HOURS == 6
        assert mock_blob.generate_signed_url.call_args.kwargs[
            "expiration"
        ] == datetime.timedelta(hours=6)

        # Cache hit within 5h45m returns exact same URL without calling storage.
        url2 = signer.generate_presigned_url("gs://bucket/a.webp")
        assert url2 == "https://signed/first"
        assert mock_blob.generate_signed_url.call_count == 1

        # Simulate entry inside the final 15-minute refresh buffer.
        key = ("gs://bucket/a.webp", 6, "GET")
        IamSignerCredentials._url_cache[key] = (
            "https://signed/first",
            datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(minutes=10),
        )

        url3 = signer.generate_presigned_url("gs://bucket/a.webp")
        assert url3 == "https://signed/refreshed"
        assert mock_blob.generate_signed_url.call_count == 2


def test_lru_cache_eviction(monkeypatch):
    monkeypatch.setattr(signer_mod, "_MAX_URL_CACHE_SIZE", 2)
    with patch.object(signer_mod.storage, "Client") as storage_cls:
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.side_effect = [
            "https://signed/1",
            "https://signed/2",
            "https://signed/3",
            "https://signed/2-again",
        ]
        storage_cls.return_value.bucket.return_value.blob.return_value = (
            mock_blob
        )

        signer = IamSignerCredentials()
        signer.generate_presigned_url("gs://b/1")
        signer.generate_presigned_url("gs://b/2")
        # Touch gs://b/1 so gs://b/2 becomes least-recently-used.
        assert signer.generate_presigned_url("gs://b/1") == "https://signed/1"
        signer.generate_presigned_url("gs://b/3")

        assert len(IamSignerCredentials._url_cache) == 2
        assert ("gs://b/1", 6, "GET") in IamSignerCredentials._url_cache
        assert ("gs://b/3", 6, "GET") in IamSignerCredentials._url_cache
        assert ("gs://b/2", 6, "GET") not in IamSignerCredentials._url_cache


@pytest.mark.anyio
async def test_generate_presigned_url_async_dedup_and_fast_path():
    signer = IamSignerCredentials()
    call_count = 0
    call_lock = threading.Lock()

    def slow_sign(version, expiration, method, credentials):
        del version, expiration, method, credentials
        nonlocal call_count
        time.sleep(0.05)
        with call_lock:
            call_count += 1
            return f"https://signed/{call_count}"

    with patch.object(signer_mod.storage, "Client") as storage_cls:
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.side_effect = slow_sign
        storage_cls.return_value.bucket.return_value.blob.return_value = (
            mock_blob
        )

        # Concurrent async calls for the same uncached URI share one task.
        results = await asyncio.gather(
            *[
                signer.generate_presigned_url_async("gs://b/same.webp")
                for _ in range(8)
            ]
        )
        assert results == ["https://signed/1"] * 8
        assert call_count == 1

        # Subsequent call hits cache without touching executor.
        with patch.object(
            asyncio.get_running_loop(), "run_in_executor"
        ) as exec_spy:
            cached = await signer.generate_presigned_url_async(
                "gs://b/same.webp"
            )
            non_gcs = await signer.generate_presigned_url_async(
                "https://youtube.com/watch?v=1"
            )
            assert cached == "https://signed/1"
            assert non_gcs == "https://youtube.com/watch?v=1"
            exec_spy.assert_not_called()


@pytest.mark.anyio
async def test_generate_presigned_url_async_cancellation_isolated():
    signer = IamSignerCredentials()
    started = threading.Event()
    release = threading.Event()

    def slow_sign(version, expiration, method, credentials):
        del version, expiration, method, credentials
        started.set()
        assert release.wait(timeout=2.0)
        return "https://signed/isolated"

    with patch.object(signer_mod.storage, "Client") as storage_cls:
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.side_effect = slow_sign
        storage_cls.return_value.bucket.return_value.blob.return_value = (
            mock_blob
        )

        task1 = asyncio.create_task(
            signer.generate_presigned_url_async("gs://b/shared.webp")
        )
        task2 = asyncio.create_task(
            signer.generate_presigned_url_async("gs://b/shared.webp")
        )
        while not started.is_set():
            await asyncio.sleep(0.005)

        task1.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task1

        release.set()
        assert await task2 == "https://signed/isolated"
        mock_blob.generate_signed_url.assert_called_once()


def test_sign_bytes_and_error_fallback():
    with (
        patch.object(
            signer_mod.iam_credentials_v1, "IAMCredentialsClient"
        ) as iam_cls,
        patch.object(signer_mod.storage, "Client") as storage_cls,
    ):
        iam_cls.return_value.sign_blob.side_effect = RuntimeError("IAM denied")

        def run_sign(version, expiration, method, credentials):
            del version, expiration, method
            return credentials.sign_bytes(b"payload").decode("utf-8")

        mock_blob = MagicMock()
        mock_blob.generate_signed_url.side_effect = run_sign
        storage_cls.return_value.bucket.return_value.blob.return_value = (
            mock_blob
        )

        signer = IamSignerCredentials()
        # Failures fall back cleanly to the original GCS URI and are not cached.
        result = signer.generate_presigned_url("gs://bucket/fail.png")
        assert result == "gs://bucket/fail.png"
        assert ("gs://bucket/fail.png", 6, "GET") not in (
            IamSignerCredentials._url_cache
        )

        # Successful sign_bytes returns signed_blob bytes.
        iam_cls.return_value.sign_blob.side_effect = None
        iam_cls.return_value.sign_blob.return_value = MagicMock(
            signed_blob=b"signed-ok"
        )
        assert signer.sign_bytes(b"payload") == b"signed-ok"


def test_generate_v4_upload_signed_url_uses_shared_storage_client():
    with patch.object(signer_mod.storage, "Client") as storage_cls:
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = "https://put-signed"
        storage_cls.return_value.bucket.return_value.blob.return_value = (
            mock_blob
        )

        signer = IamSignerCredentials()
        url, gcs_uri = signer.generate_v4_upload_signed_url(
            "uploads/a.png", "image/png", "my-bucket"
        )
        assert url == "https://put-signed"
        assert gcs_uri == "gs://my-bucket/uploads/a.png"
        storage_cls.assert_called_once()


def test_generate_presigned_url_sync_multithread_inflight_dedup_and_error_wakeup():
    from concurrent.futures import ThreadPoolExecutor

    signer = IamSignerCredentials()
    started = threading.Event()
    release = threading.Event()
    sign_calls = 0
    call_lock = threading.Lock()

    def blocking_sign(version, expiration, method, credentials):
        del version, expiration, method, credentials
        nonlocal sign_calls
        with call_lock:
            sign_calls += 1
        started.set()
        assert release.wait(timeout=2.0)
        return "https://signed/sync-shared"

    with patch.object(signer_mod.storage, "Client") as storage_cls:
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.side_effect = blocking_sign
        storage_cls.return_value.bucket.return_value.blob.return_value = (
            mock_blob
        )

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(signer.generate_presigned_url, "gs://b/sync.webp")
                for _ in range(4)
            ]
            assert started.wait(timeout=2.0)
            time.sleep(0.05)
            release.set()
            results = [f.result(timeout=2.0) for f in futures]

        assert results == ["https://signed/sync-shared"] * 4
        assert sign_calls == 1

    # On signing failure, waiting threads wake up cleanly without 30s timeout and return original URI.
    signer_mod.clear_signer_cache()
    started.clear()
    release.clear()

    def failing_sign(version, expiration, method, credentials):
        del version, expiration, method, credentials
        started.set()
        assert release.wait(timeout=2.0)
        raise RuntimeError("boom")

    with patch.object(signer_mod.storage, "Client") as storage_cls:
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.side_effect = failing_sign
        storage_cls.return_value.bucket.return_value.blob.return_value = (
            mock_blob
        )

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [
                pool.submit(
                    signer.generate_presigned_url, "gs://b/sync-fail.webp"
                )
                for _ in range(3)
            ]
            assert started.wait(timeout=2.0)
            time.sleep(0.05)
            release.set()
            results = [f.result(timeout=2.0) for f in futures]

        assert results == ["gs://b/sync-fail.webp"] * 3
