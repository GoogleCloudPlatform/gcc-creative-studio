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


import datetime
import logging
from os import getenv

from google.auth import credentials
from google.cloud import iam_credentials_v1, storage

logger = logging.getLogger(__name__)


class IamSignerCredentials(credentials.Signing):
    """A custom credentials class that uses the IAM Credentials API to
    sign bytes. This is used for generating **DOWNLOAD (GET)** presigned
    URLs.

    This pattern allows the backend's service account to generate URLs
    signed by a *different* service account (`SIGNING_SA_EMAIL`), which
    only has read access. This separates the permission to grant read
    access from the backend's other permissions.
    """

    # In-memory cache for presigned URLs (persists across dependency injections)
    # Key: (gcs_uri, expiration_hours, method)
    # Value: (url, expiry_timestamp)
    _url_cache: dict[tuple[str, int, str], tuple[str, datetime.datetime]] = {}

    def __init__(self):
        # 1. Create the custom credentials object for signing.
        self.service_account_email = getenv("SIGNING_SA_EMAIL", "")
        self.iam_client = iam_credentials_v1.IAMCredentialsClient()
        self._sa_path = (
            f"projects/-/serviceAccounts/{self.service_account_email}"
        )

    def _get_cached_url(
        self,
        gcs_uri: str,
        expiration_hours: int,
        method: str = "GET",
    ) -> str | None:
        """Retrieves a valid cached URL if available."""
        cache_key = (gcs_uri, expiration_hours, method)
        if cache_key in self._url_cache:
            url, expiry = self._url_cache[cache_key]
            # Add a 5-minute buffer before actual expiration
            if datetime.datetime.now() < (
                expiry - datetime.timedelta(minutes=5)
            ):
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
        """Caches a newly generated URL."""
        cache_key = (gcs_uri, expiration_hours, method)
        expiry = datetime.datetime.now() + datetime.timedelta(
            hours=expiration_hours
        )
        self._url_cache[cache_key] = (url, expiry)

    def generate_presigned_url(
        self,
        gcs_uri: str | None,
        expiration_hours: int = 72,
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
        if not gcs_uri or (gcs_uri and not gcs_uri.startswith("gs://")):
            return gcs_uri or ""

        # Check cache first
        cached_url = self._get_cached_url(gcs_uri, expiration_hours)
        if cached_url:
            return cached_url

        # Get the service account email from an environment variable.
        if not self.service_account_email:
            return gcs_uri

        try:
            # 2. Parse the GCS URI and create a blob object.
            storage_client = storage.Client()
            bucket_name, blob_name = gcs_uri.replace("gs://", "").split("/", 1)
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            # 3. Generate the signed URL, passing the custom credentials.
            logger.info(
                "Generating presigned URL for %s (not in cache)", gcs_uri
            )
            url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(hours=expiration_hours),
                method="GET",
                credentials=self,
            )

            # Cache the result
            self._set_cached_url(gcs_uri, expiration_hours, url)
            return url
        except Exception as e:
            logger.error(
                "Error generating presigned URL for %s: %s", gcs_uri, e
            )
            return gcs_uri

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
            storage_client = storage.Client()
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
