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
"""Tests for Media Utils."""


from unittest.mock import MagicMock, patch

from src.common.media_utils import (
    concatenate_videos,
    format_api_error_message,
    generate_image_thumbnail_bytes,
    generate_image_thumbnail_from_gcs,
    generate_thumbnail,
    get_video_dimensions,
)


def test_generate_image_thumbnail_bytes_success():
    with patch("src.common.media_utils.PILImage.open") as mock_open:
        mock_img = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_img

        # mock_img.save should write to output
        def fake_save(output, format, **kwargs):
            output.write(b"thumbdata")

        mock_img.save.side_effect = fake_save
        mock_img.mode = "RGB"

        res = generate_image_thumbnail_bytes(b"fakebytes", "image/png")

        assert res == b"thumbdata"
        mock_img.thumbnail.assert_called_once_with((512, 512))


def test_generate_image_thumbnail_bytes_error():
    with patch("src.common.media_utils.PILImage.open") as mock_open:
        mock_open.side_effect = Exception("Pillow Error")
        res = generate_image_thumbnail_bytes(b"fakebytes", "image/png")
        assert res is None


def test_generate_image_thumbnail_from_gcs_success():
    mock_gcs = MagicMock()
    mock_gcs.download_bytes_from_gcs.return_value = b"fakeimage"
    mock_gcs.upload_bytes_to_gcs.return_value = (
        "gs://bucket/image_thumbnail.png"
    )

    with patch(
        "src.common.media_utils.generate_image_thumbnail_bytes",
    ) as mock_gen_bytes:
        mock_gen_bytes.return_value = b"fakethumb"

        res = generate_image_thumbnail_from_gcs(
            mock_gcs,
            "gs://bucket/image.png",
            "image/png",
        )

        assert res == "gs://bucket/image_thumbnail.png"
        mock_gcs.upload_bytes_to_gcs.assert_called_once_with(
            b"fakethumb",
            "image_thumbnail.png",
            "image/png",
        )


def test_generate_image_thumbnail_from_gcs_download_fail():
    mock_gcs = MagicMock()
    mock_gcs.download_bytes_from_gcs.return_value = None
    res = generate_image_thumbnail_from_gcs(
        mock_gcs,
        "gs://bucket/image.png",
        "image/png",
    )
    assert res is None


def test_generate_thumbnail_video_success():
    with patch("src.common.media_utils.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0

        res = generate_thumbnail("/tmp/video.mp4")

        assert res == "/tmp/thumbnail_video.png"
        mock_run.assert_called_once()


def test_generate_thumbnail_video_empty():
    res = generate_thumbnail("")
    assert res is None


def test_concatenate_videos_success():
    with patch("src.common.media_utils.subprocess.run") as mock_run:
        with patch(
            "src.common.media_utils.open", create=True
        ) as mock_file_open:
            mock_run.return_value.returncode = 0
            res = concatenate_videos(
                ["/tmp/v1.mp4", "/tmp/v2.mp4"], "/tmp/output.mp4"
            )
            assert res == "/tmp/output.mp4"
            mock_run.assert_called_once()


def test_concatenate_videos_too_few():
    res = concatenate_videos(["/tmp/v1.mp4"], "/tmp/output.mp4")
    assert res is None


def test_get_video_dimensions_success():
    with patch("src.common.media_utils.subprocess.run") as mock_run:
        mock_run.return_value.stdout = (
            '{"streams": [{"width": 1920, "height": 1080}]}'
        )

        width, height = get_video_dimensions("/tmp/video.mp4")

        assert width == 1920
        assert height == 1080


def test_generate_image_thumbnail_from_gcs_exception():
    mock_gcs = MagicMock()
    mock_gcs.download_bytes_from_gcs.side_effect = Exception("Generic Error")
    res = generate_image_thumbnail_from_gcs(
        mock_gcs,
        "gs://bucket/image.png",
        "image/png",
    )
    assert res is None


def test_generate_thumbnail_ffmpeg_not_found():
    with patch("src.common.media_utils.subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError()
        res = generate_thumbnail("/tmp/video.mp4")
        assert res is None


def test_generate_thumbnail_called_process_error():
    with patch("src.common.media_utils.subprocess.run") as mock_run:
        import subprocess

        mock_run.side_effect = subprocess.CalledProcessError(
            1, "cmd", stderr="error"
        )
        res = generate_thumbnail("/tmp/video.mp4")
        assert res is None


def test_concatenate_videos_ffmpeg_not_found():
    with patch("src.common.media_utils.subprocess.run") as mock_run:
        with patch(
            "src.common.media_utils.open", create=True
        ) as mock_file_open:
            mock_run.side_effect = FileNotFoundError()
            res = concatenate_videos(
                ["/tmp/v1.mp4", "/tmp/v2.mp4"], "/tmp/output.mp4"
            )
            assert res is None


def test_concatenate_videos_called_process_error():
    with patch("src.common.media_utils.subprocess.run") as mock_run:
        with patch(
            "src.common.media_utils.open", create=True
        ) as mock_file_open:
            import subprocess

            mock_run.side_effect = subprocess.CalledProcessError(
                1,
                "cmd",
                stderr="error",
            )
            res = concatenate_videos(
                ["/tmp/v1.mp4", "/tmp/v2.mp4"], "/tmp/output.mp4"
            )
            assert res is None


def test_format_api_error_message_content_blocked():
    raw_error = "Error code: 400 - {'error': {'message': \"Unable to show the generated video. The output contains certain restricted individuals that violate Google's Responsible AI practices. Try rephrasing the prompt. If you think this was an error, send feedback.\", 'code': 'content_blocked'}}"
    msg = format_api_error_message(Exception(raw_error))
    assert (
        msg
        == "Unable to show the generated video. The output contains certain restricted individuals that violate Google's Responsible AI practices. Try rephrasing the prompt. If you think this was an error, send feedback."
    )


def test_format_api_error_message_restricted_individuals_fallback():
    raw_error = "error: restricted individuals present"
    msg = format_api_error_message(raw_error)
    assert "restricted individuals" in msg


def test_format_api_error_message_none():
    msg = format_api_error_message(None)
    assert "Unknown error" in msg


def test_format_api_error_message_plain():
    msg = format_api_error_message(Exception("Standard failure message"))
    assert msg == "Standard failure message"
