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
"""IAM Signer credentials provider for GCS."""


import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import datetime
import logging
from os import getenv
import threading

from google.auth import credentials
from google.cloud import iam_credentials_v1, storage

logger = logging.getLogger(__name__)

DEFAULT_PRESIGNED_EXPIRATION_HOURS = 6
_CACHE_REFRESH_BUFFER = datetime.timedelta(minutes=15)
_MAX_URL_CACHE_SIZE = 10_000

_signing_executor: ThreadPoolExecutor | None = None
_client_lock = threading.Lock()
_cache_lock = threading.Lock()
_inflight_lock = threading.Lock()
_shared_iam_client: iam_credentials_v1.IAMCredentialsClient | None = None
_shared_storage_client: storage.Client | None = None
_inflight_futures: dict[
    tuple[int, tuple[str, int, str]], asyncio.Future[str]
] = {}


def _get_signing_executor() -> ThreadPoolExecutor:
    """Returns the lazily initialized thread pool used for GCS URL signing."""
    global _signing_executor  # pylint: disable=global-statement
    with _client_lock:
        if _signing_executor is None:
            _signing_executor = ThreadPoolExecutor(
                max_workers=32, thread_name_prefix="gcs-sign"
            )
        return _signing_executor


def shutdown_signing_executor() -> None:
    """Shuts down the shared GCS URL signing thread pool during app teardown."""
    global _signing_executor  # pylint: disable=global-statement
    with _client_lock:
        executor = _signing_executor
        _signing_executor = None
    if executor is not None:
        executor.shutdown(wait=False)


def _get_iam_client() -> iam_credentials_v1.IAMCredentialsClient:
    """Returns the lazy singleton IAM Credentials client."""
    global _shared_iam_client  # pylint: disable=global-statement
    with _client_lock:
        if _shared_iam_client is None:
            _shared_iam_client = iam_credentials_v1.IAMCredentialsClient()
        return _shared_iam_client


def _get_storage_client() -> storage.Client:
    """Returns the lazy singleton GCS client."""
    global _shared_storage_client  # pylint: disable=global-statement
    with _client_lock:
        if _shared_storage_client is None:
            _shared_storage_client = storage.Client()
        return _shared_storage_client


def clear_signer_cache() -> None:
    """Clears cached presigned URLs, in-flight deduplication state, and clients."""
    global _shared_iam_client, _shared_storage_client  # pylint: disable=global-statement
    with _cache_lock:
        IamSignerCredentials.clear_url_cache()
    with _inflight_lock:
        _inflight_futures.clear()
    with _client_lock:
        _shared_iam_client = None
        _shared_storage_client = None


class IamSignerCredentials(credentials.Signing):
    """A custom credentials class that uses the IAM Credentials API to
    sign bytes. This is used for generating **DOWNLOAD (GET)** presigned
    URLs.

    This pattern allows the backend's service account to generate URLs
    signed by a *different* service account (`SIGNING_SA_EMAIL`), which
    only has read access. This separates the permission to grant read
    access from the backend's other permissions.
    """

    # Process-wide LRU cache for presigned URLs (persists across DI instances)
    # Key: (gcs_uri, expiration_hours, method)
    # Value: (url, expiry_timestamp)
    _url_cache: OrderedDict[
        tuple[str, int, str], tuple[str, datetime.datetime]
    ] = OrderedDict()

    @classmethod
    def clear_url_cache(cls) -> None:
        """Empties the shared presigned URL cache."""
        cls._url_cache.clear()

    def __init__(self):
        # Defer cloud client initialization until an actual cache miss needs it.
        self.service_account_email = getenv("SIGNING_SA_EMAIL", "")
        self._sa_path = (
            f"projects/-/serviceAccounts/{self.service_account_email}"
        )

    @property
    def iam_client(self) -> iam_credentials_v1.IAMCredentialsClient:
        """Lazily returns the shared IAM Credentials client."""
        return _get_iam_client()

    def _get_cached_url(
        self,
        gcs_uri: str,
        expiration_hours: int,
        method: str = "GET",
    ) -> str | None:
        """Retrieves a valid cached URL if available."""
        cache_key = (gcs_uri, expiration_hours, method)
        now = datetime.datetime.now(datetime.UTC)
        with _cache_lock:
            entry = self._url_cache.get(cache_key)
            if entry is None:
                return None
            url, expiry = entry
            # Refresh proactively before actual expiration
            if now < (expiry - _CACHE_REFRESH_BUFFER):
                self._url_cache.move_to_end(cache_key)
                return url
            del self._url_cache[cache_key]
        return None

    def _set_cached_url(
        self,
        gcs_uri: str,
        expiration_hours: int,
        url: str,
        method: str = "GET",
    ):
        """Caches a newly generated URL with bounded LRU eviction."""
        cache_key = (gcs_uri, expiration_hours, method)
        expiry = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            hours=expiration_hours
        )
        with _cache_lock:
            self._url_cache[cache_key] = (url, expiry)
            self._url_cache.move_to_end(cache_key)
            while len(self._url_cache) > _MAX_URL_CACHE_SIZE:
                self._url_cache.popitem(last=False)

    def generate_presigned_url(
        self,
        gcs_uri: str | None,
        expiration_hours: int = DEFAULT_PRESIGNED_EXPIRATION_HOURS,
    ) -> str:
        """Generates a v4 presigned URL for a GCS object.

        The user or service account running this code needs
        'roles/storage.objectViewer' permission on the bucket, or a custom
        role with 'storage.objects.get'. The principal running this code
        needs 'roles/iam.serviceAccountTokenCreator' on the
        `SIGNING_SA_EMAIL` service account.

        Args:
            gcs_uri: The GCS URI of the object (e.g., 'gs://bucket/object').
            expiration_hours: The number of hours the URL will be valid for.

        Returns:
            A presigned URL, or the original GCS URI if an error occurs.

        """
        if not gcs_uri or not gcs_uri.startswith("gs://"):
            return gcs_uri or ""

        if not self.service_account_email:
            return gcs_uri

        cached_url = self._get_cached_url(gcs_uri, expiration_hours)
        if cached_url:
            return cached_url

        try:
            storage_client = _get_storage_client()
            bucket_name, blob_name = gcs_uri.removeprefix("gs://").split("/", 1)
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            logger.info(
                "Generating presigned URL for %s (not in cache)", gcs_uri
            )
            url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(hours=expiration_hours),
                method="GET",
                credentials=self,
            )

            self._set_cached_url(gcs_uri, expiration_hours, url)
            return url
        except Exception as e:
            logger.error(
                "Error generating presigned URL for %s: %s", gcs_uri, e
            )
            return gcs_uri

    async def generate_presigned_url_async(
        self,
        gcs_uri: str | None,
        expiration_hours: int = DEFAULT_PRESIGNED_EXPIRATION_HOURS,
    ) -> str:
        """Asynchronously resolves a presigned URL using the signing pool.

        Cache hits and non-GCS URIs return immediately without scheduling
        thread-pool work. Concurrent requests for the same uncached URI on an
        event loop share a single signing task.
        """
        if not gcs_uri or not gcs_uri.startswith("gs://"):
            return gcs_uri or ""

        if not self.service_account_email:
            return gcs_uri

        cached_url = self._get_cached_url(gcs_uri, expiration_hours)
        if cached_url:
            return cached_url

        loop = asyncio.get_running_loop()
        cache_key = (gcs_uri, expiration_hours, "GET")
        inflight_key = (id(loop), cache_key)
        with _inflight_lock:
            inflight = _inflight_futures.get(inflight_key)
            if inflight is None or inflight.done():
                inflight = loop.run_in_executor(
                    _get_signing_executor(),
                    self.generate_presigned_url,
                    gcs_uri,
                    expiration_hours,
                )
                _inflight_futures[inflight_key] = inflight

                def _cleanup(done_fut: asyncio.Future[str]) -> None:
                    with _inflight_lock:
                        if _inflight_futures.get(inflight_key) is done_fut:
                            _inflight_futures.pop(inflight_key, None)
                    if not done_fut.cancelled():
                        _ = done_fut.exception()

                inflight.add_done_callback(_cleanup)

        return await asyncio.shield(inflight)

    def generate_v4_upload_signed_url(
        self,
        destination_blob_name: str,
        content_type: str,
        bucket_name: str,
        expiration_hours: int = 72,
    ) -> tuple[str | None, str | None]:
        """Generates a v4 signed URL for a client-side **UPLOAD (PUT)**.

        This method uses the custom signing mechanism of this class to
        generate a URL, which works in environments without a private key
        (like local dev).

        The service account running this code needs
        `roles/iam.serviceAccountTokenCreator` on the `SIGNING_SA_EMAIL`
        service account. The `SIGNING_SA_EMAIL` service account needs
        `roles/storage.objectCreator` on the bucket.

        Args:
            destination_blob_name: The desired name for the object in GCS.
            content_type: The MIME type of the file to be uploaded.
            bucket_name: The name of the target GCS bucket.
            expiration_hours: How long the URL should be valid.

        Returns:
            A tuple containing the presigned URL for the PUT request and the
            final GCS URI of the object, or (None, None) on failure.

        """
        if not self.service_account_email:
            logger.error(
                "SIGNING_SA_EMAIL is not set. Cannot generate upload URL."
            )
            return None, None

        try:
            storage_client = _get_storage_client()
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(destination_blob_name)

            url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(hours=expiration_hours),
                method="PUT",
                content_type=content_type,
                credentials=self,  # Use the custom signer
            )
            gcs_uri = f"gs://{bucket_name}/{destination_blob_name}"
            return url, gcs_uri
        except Exception as e:
            logger.error(
                "Failed to generate v4 upload signed URL: %s", e, exc_info=True
            )
            return None, None

    @property
    def signer_email(self) -> str:
        """The email of the service account used for signing."""
        return self.service_account_email

    def sign_bytes(self, message: bytes) -> bytes:
        """Signs a bytestring using the IAM Credentials API."""
        try:
            response = self.iam_client.sign_blob(
                name=self._sa_path,
                payload=message,
            )
            return response.signed_blob
        except Exception as e:
            logger.error(
                "IAM PERMISSION DENIED: The principal running this code "
                "does not have "
                "'roles/iam.serviceAccountTokenCreator' on the service "
                "account '%s'.",
                self.service_account_email,
            )
            raise e  # Re-raise the exception to be caught by the caller

    # Alias sign_bytes to sign to satisfy the Signer interface, which is
    # required by the `signer` property.
    sign = sign_bytes

    @property
    def signer(self):
        """The object that can sign bytes."""
        return self

    def refresh(self, request):
        """Refresh is not used by this credentials type."""
