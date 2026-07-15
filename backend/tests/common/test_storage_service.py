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
"""Tests for Storage Service."""


from unittest.mock import MagicMock, patch

import pytest
from google.api_core import exceptions

from src.common.storage_service import GcsService


@pytest.fixture(name="gcs_service")
def fixture_gcs_service():
    with patch("src.common.storage_service.storage.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        service = GcsService(bucket_name="test-bucket")
        service.mock_client = mock_client
        yield service


def test_download_from_gcs_success(gcs_service):
    mock_blob = MagicMock()
    gcs_service.bucket.blob.return_value = mock_blob

    with patch("src.common.storage_service.os.makedirs"):
        res = gcs_service.download_from_gcs("path/file.txt", "/tmp/local.txt")

        assert res == "/tmp/local.txt"
        mock_blob.download_to_filename.assert_called_once_with("/tmp/local.txt")


def test_download_from_gcs_not_found(gcs_service):
    mock_blob = MagicMock()
    mock_blob.download_to_filename.side_effect = exceptions.NotFound(
        "Not found"
    )
    gcs_service.bucket.blob.return_value = mock_blob

    with patch("src.common.storage_service.os.makedirs"):
        res = gcs_service.download_from_gcs("path/file.txt", "/tmp/local.txt")
        assert res is None


def test_download_bytes_from_gcs_success(gcs_service):
    # Setup mock blob download_as_bytes
    mock_blob = MagicMock()
    mock_blob.download_as_bytes.return_value = b"somebytes"

    # Mock return value of self.client.bucket()
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    gcs_service.client.bucket.return_value = mock_bucket

    res = gcs_service.download_bytes_from_gcs("gs://another-bucket/file.txt")

    assert res == b"somebytes"
    mock_bucket.blob.assert_called_once_with("file.txt")


def test_download_bytes_from_gcs_invalid_uri(gcs_service):
    res = gcs_service.download_bytes_from_gcs("http://example.com")
    assert res is None


def test_download_bytes_from_gcs_not_found(gcs_service):
    mock_blob = MagicMock()
    mock_blob.download_as_bytes.side_effect = exceptions.NotFound("Not found")

    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    gcs_service.client.bucket.return_value = mock_bucket

    res = gcs_service.download_bytes_from_gcs("gs://bucket/file.txt")
    assert res is None


def test_upload_file_to_gcs_success(gcs_service):
    mock_blob = MagicMock()
    gcs_service.bucket.blob.return_value = mock_blob

    with patch("src.common.storage_service.pathlib.Path") as mock_path:
        mock_path.return_value.is_file.return_value = True

        res = gcs_service.upload_file_to_gcs(
            "/tmp/local.txt",
            "remote.txt",
            "text/plain",
        )

        assert res == "gs://test-bucket/remote.txt"
        mock_blob.upload_from_filename.assert_called_once_with(
            "/tmp/local.txt",
            content_type="text/plain",
        )


def test_upload_file_to_gcs_not_found(gcs_service):
    mock_blob = MagicMock()
    mock_blob.upload_from_filename.side_effect = exceptions.NotFound(
        "Not found"
    )
    gcs_service.bucket.blob.return_value = mock_blob

    with patch("src.common.storage_service.pathlib.Path") as mock_path:
        mock_path.return_value.is_file.return_value = True

        res = gcs_service.upload_file_to_gcs(
            "/tmp/local.txt",
            "remote.txt",
            "text/plain",
        )
        assert res is None


def test_upload_bytes_to_gcs_success(gcs_service):
    mock_blob = MagicMock()
    gcs_service.bucket.blob.return_value = mock_blob

    res = gcs_service.upload_bytes_to_gcs(b"hello", "remote.txt", "text/plain")

    assert res == "gs://test-bucket/remote.txt"
    mock_blob.upload_from_string.assert_called_once_with(
        b"hello",
        content_type="text/plain",
    )


def test_delete_blob_from_uri_success(gcs_service):
    mock_blob = MagicMock()
    gcs_service.bucket.blob.return_value = mock_blob

    res = gcs_service.delete_blob_from_uri("gs://test-bucket/file.txt")

    assert res is True
    mock_blob.delete.assert_called_once()


def test_delete_blob_from_uri_invalid_bucket(gcs_service):
    res = gcs_service.delete_blob_from_uri("gs://other-bucket/file.txt")
    assert res is False


def test_upload_file_to_gcs_no_bucket(gcs_service):
    gcs_service.bucket_name = None
    res = gcs_service.upload_file_to_gcs(
        "/tmp/local.txt", "remote.txt", "text/plain"
    )
    assert res is None


def test_upload_file_to_gcs_file_not_found_raise(gcs_service):
    with patch("src.common.storage_service.pathlib.Path") as mock_path:
        mock_path.return_value.is_file.return_value = False
        with pytest.raises(FileNotFoundError):
            gcs_service.upload_file_to_gcs(
                "/tmp/local.txt", "remote.txt", "text/plain"
            )


def test_upload_file_to_gcs_api_error(gcs_service):
    mock_blob = MagicMock()
    mock_blob.upload_from_filename.side_effect = exceptions.GoogleAPICallError(
        "API error",
    )
    gcs_service.bucket.blob.return_value = mock_blob

    with patch("src.common.storage_service.pathlib.Path") as mock_path:
        mock_path.return_value.is_file.return_value = True
        res = gcs_service.upload_file_to_gcs(
            "/tmp/local.txt",
            "remote.txt",
            "text/plain",
        )
        assert res is None


def test_upload_bytes_to_gcs_api_error(gcs_service):
    mock_blob = MagicMock()
    mock_blob.upload_from_string.side_effect = exceptions.GoogleAPICallError(
        "Error"
    )
    gcs_service.bucket.blob.return_value = mock_blob

    res = gcs_service.upload_bytes_to_gcs(b"hello", "remote.txt", "text/plain")
    assert res is None


def test_upload_bytes_to_gcs_not_found(gcs_service):
    mock_blob = MagicMock()
    mock_blob.upload_from_string.side_effect = exceptions.NotFound("Not found")
    gcs_service.bucket.blob.return_value = mock_blob
    res = gcs_service.upload_bytes_to_gcs(b"hello", "remote.txt", "text/plain")
    assert res is None


def test_delete_blob_from_uri_not_found_catch(gcs_service):
    mock_blob = MagicMock()
    mock_blob.delete.side_effect = exceptions.NotFound("Not found")
    gcs_service.bucket.blob.return_value = mock_blob
    res = gcs_service.delete_blob_from_uri("gs://test-bucket/file.txt")
    assert res is True


def test_delete_blob_from_uri_api_error(gcs_service):
    mock_blob = MagicMock()
    mock_blob.delete.side_effect = exceptions.GoogleAPICallError("Error")
    gcs_service.bucket.blob.return_value = mock_blob
    res = gcs_service.delete_blob_from_uri("gs://test-bucket/file.txt")
    assert res is False


def test_store_to_gcs_bytes_success(gcs_service):
    mock_blob = MagicMock()
    gcs_service.bucket.blob.return_value = mock_blob
    res = gcs_service.store_to_gcs("folder", "file.txt", "text/plain", b"bytes")
    assert res == "gs://test-bucket/folder/file.txt"
    mock_blob.upload_from_string.assert_called_once_with(
        b"bytes",
        content_type="text/plain",
    )


def test_store_to_gcs_decode_success(gcs_service):
    mock_blob = MagicMock()
    gcs_service.bucket.blob.return_value = mock_blob
    import base64

    encoded = base64.b64encode(b"hello").decode()
    res = gcs_service.store_to_gcs(
        "folder",
        "file.txt",
        "text/plain",
        encoded,
        decode=True,
    )
    assert res == "gs://test-bucket/folder/file.txt"
    mock_blob.upload_from_string.assert_called_once_with(
        b"hello",
        content_type="text/plain",
    )


def test_store_to_gcs_invalid_type(gcs_service):
    res = gcs_service.store_to_gcs("folder", "file.txt", "text/plain", 123)
    assert res == ""
