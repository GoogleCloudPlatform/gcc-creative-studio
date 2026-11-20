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


import io
import os
import shutil
import subprocess
import tracemalloc
from unittest.mock import MagicMock, patch

from PIL import Image
import pytest

from src.common.media_utils import (
    VIDEO_THUMBNAIL_EXT,
    VIDEO_THUMBNAIL_MIME_TYPE,
    concatenate_videos,
    extract_youtube_video_id,
    format_api_error_message,
    generate_image_thumbnail_bytes,
    generate_image_thumbnail_from_gcs,
    generate_thumbnail,
    generate_video_thumbnail_from_gcs,
    get_video_dimensions,
    get_youtube_aspect_ratio,
)


def test_generate_image_thumbnail_bytes_success():
    buf = io.BytesIO()
    Image.new("RGB", (1024, 512), color=(10, 20, 30)).save(buf, format="PNG")
    res = generate_image_thumbnail_bytes(buf.getvalue())

    assert res is not None
    assert res[:4] == b"RIFF"
    with Image.open(io.BytesIO(res)) as out:
        assert out.format == "WEBP"
        assert max(out.size) <= 512
        assert out.size == (512, 256)


def test_generate_image_thumbnail_bytes_preserves_alpha_and_exif():
    # RGBA alpha preserved
    rgba_buf = io.BytesIO()
    Image.new("RGBA", (600, 300), color=(255, 0, 0, 128)).save(
        rgba_buf, format="PNG"
    )
    rgba_webp = generate_image_thumbnail_bytes(rgba_buf.getvalue())
    assert rgba_webp is not None
    with Image.open(io.BytesIO(rgba_webp)) as out:
        assert out.format == "WEBP"
        assert out.mode == "RGBA"
        assert out.size == (512, 256)

    # EXIF orientation 6 (Rotate 90 CW -> 800x400 becomes 400x800 -> 256x512)
    exif_img = Image.new("RGB", (800, 400), color=(0, 128, 255))
    exif = exif_img.getexif()
    exif[0x0112] = 6
    exif_buf = io.BytesIO()
    exif_img.save(exif_buf, format="JPEG", exif=exif.tobytes())

    rotated_webp = generate_image_thumbnail_bytes(exif_buf.getvalue())
    assert rotated_webp is not None
    with Image.open(io.BytesIO(rotated_webp)) as out:
        assert out.format == "WEBP"
        assert out.size == (256, 512)


def test_generate_image_thumbnail_bytes_error():
    with patch("src.common.media_utils.PILImage.open") as mock_open:
        mock_open.side_effect = Exception("Pillow Error")
        res = generate_image_thumbnail_bytes(b"fakebytes")
        assert res is None


def test_generate_image_thumbnail_from_gcs_success():
    mock_gcs = MagicMock()
    mock_gcs.download_bytes_from_gcs.return_value = b"fakeimage"
    mock_gcs.upload_bytes_to_gcs.return_value = (
        "gs://bucket/image_thumbnail.webp"
    )

    with patch(
        "src.common.media_utils.generate_image_thumbnail_bytes",
    ) as mock_gen_bytes:
        mock_gen_bytes.return_value = b"fakethumb"

        res = generate_image_thumbnail_from_gcs(
            mock_gcs,
            "gs://bucket/image.png",
        )

        assert res == "gs://bucket/image_thumbnail.webp"
        mock_gcs.upload_bytes_to_gcs.assert_called_once_with(
            b"fakethumb",
            "image_thumbnail.webp",
            "image/webp",
        )


def test_generate_image_thumbnail_from_gcs_download_fail():
    mock_gcs = MagicMock()
    mock_gcs.download_bytes_from_gcs.return_value = None
    res = generate_image_thumbnail_from_gcs(
        mock_gcs,
        "gs://bucket/image.png",
    )
    assert res is None


def test_generate_thumbnail_video_success():
    with patch("src.common.media_utils.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0

        res = generate_thumbnail("/tmp/video.mp4")

        assert res == "/tmp/thumbnail_video.jpg"
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs.get("timeout") == 30
        cmd = mock_run.call_args.args[0]
        assert "-vf" in cmd
        expected_scale = (
            "scale='if(gt(iw,ih),min(512,iw),-2)':"
            "'if(gt(iw,ih),-2,min(512,ih))'"
        )
        assert expected_scale in cmd
        assert "-q:v" in cmd
        assert "4" in cmd


def test_generate_thumbnail_timeout():
    with patch(
        "src.common.media_utils.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=30),
    ):
        assert generate_thumbnail("/tmp/slow.mp4") is None


def test_generate_thumbnail_caps_portrait_and_landscape_dimensions(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg binary not installed")

    assert (VIDEO_THUMBNAIL_MIME_TYPE, VIDEO_THUMBNAIL_EXT) == (
        "image/jpeg",
        ".jpg",
    )

    portrait_mp4 = tmp_path / "portrait.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=1080x1920:d=0.1",
            "-frames:v",
            "1",
            str(portrait_mp4),
        ],
        check=True,
        capture_output=True,
    )
    portrait_thumb = generate_thumbnail(str(portrait_mp4))
    assert portrait_thumb is not None
    with Image.open(portrait_thumb) as img:
        assert img.size == (288, 512)

    landscape_mp4 = tmp_path / "landscape.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=1920x1080:d=0.1",
            "-frames:v",
            "1",
            str(landscape_mp4),
        ],
        check=True,
        capture_output=True,
    )
    landscape_thumb = generate_thumbnail(str(landscape_mp4))
    assert landscape_thumb is not None
    with Image.open(landscape_thumb) as img:
        assert img.size == (512, 288)


def test_generate_thumbnail_skips_when_ffmpeg_absent(tmp_path):
    with patch("shutil.which", return_value=None):
        with pytest.raises(pytest.skip.Exception):
            test_generate_thumbnail_caps_portrait_and_landscape_dimensions(
                tmp_path
            )


def test_generate_video_thumbnail_from_gcs_success():
    mock_gcs = MagicMock()
    mock_gcs.download_stream_from_gcs.return_value = iter([b"part1", b"part2"])
    mock_gcs.upload_file_to_gcs.return_value = (
        "gs://bucket/uploads/clip_thumbnail.jpg"
    )
    captured: dict[str, str] = {}

    def fake_generate_thumbnail(video_path: str) -> str:
        captured["temp_dir"] = os.path.dirname(video_path)
        thumb_path = os.path.join(captured["temp_dir"], "thumbnail_video.jpg")
        with open(thumb_path, "wb") as f:
            f.write(b"fakejpg")
        return thumb_path

    with patch(
        "src.common.media_utils.generate_thumbnail",
        side_effect=fake_generate_thumbnail,
    ):
        res = generate_video_thumbnail_from_gcs(
            mock_gcs, "gs://bucket/uploads/clip.mp4"
        )

    assert res == "gs://bucket/uploads/clip_thumbnail.jpg"
    mock_gcs.download_bytes_from_gcs.assert_not_called()
    mock_gcs.download_stream_from_gcs.assert_called_once_with(
        "gs://bucket/uploads/clip.mp4"
    )
    upload_kwargs = mock_gcs.upload_file_to_gcs.call_args.kwargs
    assert (
        upload_kwargs["destination_blob_name"] == "uploads/clip_thumbnail.jpg"
    )
    assert upload_kwargs["mime_type"] == "image/jpeg"
    assert not os.path.exists(captured["temp_dir"])


def test_generate_video_thumbnail_from_gcs_streams_without_full_buffering():
    chunk_size = 8192
    num_chunks = 4096  # 32 MiB virtual stream
    mock_gcs = MagicMock()
    mock_gcs.download_stream_from_gcs.return_value = (
        b"v" * chunk_size for _ in range(num_chunks)
    )
    mock_gcs.upload_file_to_gcs.return_value = (
        "gs://bucket/uploads/large_thumbnail.jpg"
    )
    captured: dict[str, int | str] = {}

    def fake_generate_thumbnail(video_path: str) -> str:
        captured["size"] = os.path.getsize(video_path)
        captured["temp_dir"] = os.path.dirname(video_path)
        thumb_path = os.path.join(captured["temp_dir"], "thumbnail_video.jpg")
        with open(thumb_path, "wb") as f:
            f.write(b"jpg-bytes")
        return thumb_path

    tracemalloc.start()
    try:
        with patch(
            "src.common.media_utils.generate_thumbnail",
            side_effect=fake_generate_thumbnail,
        ):
            res = generate_video_thumbnail_from_gcs(
                mock_gcs, "gs://bucket/uploads/large.mp4"
            )
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert res == "gs://bucket/uploads/large_thumbnail.jpg"
    assert captured["size"] == chunk_size * num_chunks
    assert peak_bytes < 4 * 1024 * 1024
    mock_gcs.download_bytes_from_gcs.assert_not_called()
    assert not os.path.exists(str(captured["temp_dir"]))


def test_generate_video_thumbnail_from_gcs_failures():
    mock_gcs = MagicMock()
    assert (
        generate_video_thumbnail_from_gcs(mock_gcs, "https://bad/uri") is None
    )
    assert generate_video_thumbnail_from_gcs(mock_gcs, "gs://bucket/") is None

    mock_gcs.download_stream_from_gcs.return_value = iter([])
    assert (
        generate_video_thumbnail_from_gcs(mock_gcs, "gs://bucket/a.mp4") is None
    )

    mock_gcs.download_stream_from_gcs.return_value = iter([b"video"])
    captured: dict[str, str] = {}

    def fail_generate_thumbnail(video_path: str) -> None:
        captured["temp_dir"] = os.path.dirname(video_path)
        return None

    with patch(
        "src.common.media_utils.generate_thumbnail",
        side_effect=fail_generate_thumbnail,
    ):
        assert (
            generate_video_thumbnail_from_gcs(mock_gcs, "gs://bucket/a.mp4")
            is None
        )
    assert not os.path.exists(captured["temp_dir"])


def test_generate_thumbnail_video_empty():
    res = generate_thumbnail("")
    assert res is None


def test_concatenate_videos_success():
    with (
        patch("src.common.media_utils.subprocess.run") as mock_run,
        patch("src.common.media_utils.open", create=True),
    ):
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
    )
    assert res is None


def test_generate_thumbnail_ffmpeg_not_found():
    with patch("src.common.media_utils.subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError()
        res = generate_thumbnail("/tmp/video.mp4")
        assert res is None


def test_generate_thumbnail_called_process_error():
    with patch("src.common.media_utils.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "cmd", stderr="error"
        )
        res = generate_thumbnail("/tmp/video.mp4")
        assert res is None


def test_concatenate_videos_ffmpeg_not_found():
    with (
        patch("src.common.media_utils.subprocess.run") as mock_run,
        patch("src.common.media_utils.open", create=True),
    ):
        mock_run.side_effect = FileNotFoundError()
        res = concatenate_videos(
            ["/tmp/v1.mp4", "/tmp/v2.mp4"], "/tmp/output.mp4"
        )
        assert res is None


def test_concatenate_videos_called_process_error():
    with (
        patch("src.common.media_utils.subprocess.run") as mock_run,
        patch("src.common.media_utils.open", create=True),
    ):
        mock_run.side_effect = subprocess.CalledProcessError(
            1,
            "cmd",
            stderr="error",
        )
        res = concatenate_videos(
            ["/tmp/v1.mp4", "/tmp/v2.mp4"], "/tmp/output.mp4"
        )
        assert res is None


def test_extract_youtube_video_id_valid_and_invalid():
    assert (
        extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )
    assert (
        extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )
    assert (
        extract_youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )
    assert (
        extract_youtube_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )
    assert extract_youtube_video_id("not a youtube url") is None
    assert extract_youtube_video_id(None) is None


def test_get_youtube_aspect_ratio():
    assert (
        get_youtube_aspect_ratio("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        == "16:9"
    )
    assert get_youtube_aspect_ratio("https://youtu.be/dQw4w9WgXcQ") == "16:9"
    assert (
        get_youtube_aspect_ratio("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        == "9:16"
    )
    assert get_youtube_aspect_ratio("not a youtube url") == "16:9"
    assert get_youtube_aspect_ratio(None) == "16:9"


def test_format_api_error_message_content_blocked():
    expected_msg = (
        "Unable to show the generated video. The output contains certain "
        "restricted individuals that violate Google's Responsible AI practices. "
        "Try rephrasing the prompt. If you think this was an error, "
        "send feedback."
    )
    raw_error = (
        f"Error code: 400 - {{'error': {{'message': \"{expected_msg}\", "
        "'code': 'content_blocked'}}"
    )
    msg = format_api_error_message(Exception(raw_error))
    assert msg == expected_msg


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
