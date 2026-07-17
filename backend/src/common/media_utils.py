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
"""Media processing and utility functions."""


import io
import json
import logging
import os
import pathlib
import re
import subprocess

from PIL import Image as PILImage

from google.api_core import exceptions

from src.common.storage_service import GcsService

logger = logging.getLogger(__name__)


def generate_image_thumbnail_bytes(
    image_bytes: bytes, mime_type: str
) -> bytes | None:
    """Generates a thumbnail from image bytes using PIL.

    Args:
        image_bytes: The raw bytes of the image.
        mime_type: The mime type of the image (e.g., 'image/png', 'image/jpeg').

    Returns:
        The raw bytes of the generated thumbnail, or None if it fails.

    """
    try:
        with PILImage.open(io.BytesIO(image_bytes)) as img:
            # Convert to RGB if RGBA and saving as JPEG
            if mime_type == "image/jpeg" and img.mode == "RGBA":
                img = img.convert("RGB")

            img.thumbnail((512, 512))
            output = io.BytesIO()

            format_to_save = "PNG" if mime_type == "image/png" else "JPEG"
            img.save(output, format=format_to_save, optimize=True)
            return output.getvalue()
    except Exception as e:
        logger.error("Error generating image thumbnail: %s", e)
        return None


def generate_image_thumbnail_from_gcs(
    gcs_service: GcsService,
    gcs_uri: str,
    mime_type: str,
) -> str | None:
    """Generates a thumbnail for the given GCS URI and uploads it.

    Args:
        gcs_service: The GcsService instance to use for download/upload.
        gcs_uri: The GCS URI of the source image.
        mime_type: The mime type of the image.

    Returns:
        The GCS URI of the generated thumbnail, or None if it fails.

    """
    try:
        image_bytes = gcs_service.download_bytes_from_gcs(gcs_uri)
        if not image_bytes:
            return None

        thumbnail_bytes = generate_image_thumbnail_bytes(image_bytes, mime_type)
        if not thumbnail_bytes:
            return None

        if not gcs_uri.startswith("gs://"):
            return None

        # gs://bucket/blob_name
        parts = gcs_uri.split("/", 3)  # gs:, , bucket, blob_name
        if len(parts) < 4:
            return None
        blob_name = parts[3]

        path = pathlib.Path(blob_name)
        # Use simple string manipulation to avoid path issues on different OS
        # if needed, pathlib is generally fine.
        new_blob_name = str(path.parent / f"{path.stem}_thumbnail{path.suffix}")
        if path.parent == pathlib.Path():
            new_blob_name = f"{path.stem}_thumbnail{path.suffix}"

        return gcs_service.upload_bytes_to_gcs(
            thumbnail_bytes,
            new_blob_name,
            mime_type,
        )

    except Exception as e:
        logger.error("Thumbnail generation failed: %s", e)
        return None


def generate_thumbnail(video_path: str) -> str | None:
    """Generates a thumbnail from a video file using ffmpeg.

    Args:
        video_path: The path to the video file.

    Returns:
        The path to the generated thumbnail, or None if it fails.

    """
    if not video_path:
        return None

    thumbnail_filename = (
        "thumbnail_"
        + os.path.splitext(os.path.basename(video_path))[0]
        + ".png"
    )
    thumbnail_path = os.path.join(
        os.path.dirname(video_path), thumbnail_filename
    )

    command = [
        "ffmpeg",
        "-i",
        video_path,
        "-ss",
        "00:00:00.000",  # Capture frame at 0 milisecond
        "-vframes",
        "1",
        "-y",  # Overwrite output file if it exists
        thumbnail_path,
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        return thumbnail_path
    except FileNotFoundError:
        logger.error(
            "ffmpeg not found. Please ensure ffmpeg is installed and in "
            "your PATH.",
        )
        return None
    except subprocess.CalledProcessError as e:
        logger.error("Error generating thumbnail: %s", e.stderr)
        return None


def concatenate_videos(video_paths: list[str], output_path: str) -> str | None:
    """Concatenates multiple video files into a single file using ffmpeg.

    Args:
        video_paths: An ordered list of local paths to the video files to be
            joined.
        output_path: The local path for the final concatenated video.

    Returns:
        The path to the concatenated video, or None on failure.

    """
    if not video_paths or len(video_paths) < 2:
        logger.error("Concatenation requires at least two video files.")
        return None

    # Create a temporary file to list the input videos for ffmpeg
    list_file_path = os.path.join(
        os.path.dirname(output_path), "concat_list.txt"
    )
    with open(list_file_path, "w", encoding="utf-8") as f:
        for path in video_paths:
            absolute_path = os.path.abspath(path)
            # ffmpeg requires file paths to be escaped
            f.write(f"file '{absolute_path}'\n")

    command = [
        "ffmpeg",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_file_path,
        "-c",
        "copy",  # Copy codecs to avoid re-encoding, which is much faster
        "-y",  # Overwrite output file if it exists
        output_path,
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        logger.info("Successfully concatenated videos to %s", output_path)
        return output_path
    except FileNotFoundError:
        logger.error(
            "ffmpeg not found. Please ensure ffmpeg is installed and in "
            "your PATH.",
        )
        return None
    except subprocess.CalledProcessError as e:
        logger.error("Error concatenating videos: %s", e.stderr)
        return None
    finally:
        # Clean up the temporary list file
        if os.path.exists(list_file_path):
            os.remove(list_file_path)


def get_video_dimensions(video_path: str) -> tuple[int, int]:
    """Uses ffprobe to get the width and height of a video file."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        video_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    width = data["streams"][0]["width"]
    height = data["streams"][0]["height"]
    return width, height


def extract_youtube_video_id(url: str | None) -> str | None:
    """Extracts the 11-character video ID from a YouTube URL."""
    if not url:
        return None
    trimmed = url.strip()
    try:
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(trimmed)
        hostname = parsed.hostname.lower() if parsed.hostname else ""

        is_youtube = any(
            h in hostname for h in ("youtube.com", "youtube-nocookie.com")
        )
        is_short = "youtu.be" in hostname

        if is_youtube:
            if any(p in parsed.path for p in ("/embed/", "/shorts/", "/v/")):
                parts = parsed.path.split("/")
                for p in parts:
                    if len(p) == 11:
                        return p
            query_params = parse_qs(parsed.query)
            v_list = query_params.get("v")
            if v_list and len(v_list[0]) == 11:
                return v_list[0]
        elif is_short:
            path_parts = parsed.path.strip("/").split("/")
            if path_parts and len(path_parts[0]) == 11:
                return path_parts[0]
    except Exception:
        pass
    # Regex fallback
    pattern = r"(?:youtu\.be\/|v\/|u\/\w\/|embed\/|shorts\/|watch\?v=|&v=)([a-zA-Z0-9_-]{11})"
    match = re.search(pattern, trimmed)
    return match.group(1) if match else None


def get_youtube_aspect_ratio(url: str | None) -> str:
    """Determines the aspect ratio of a YouTube video based on its URL (e.g., 9:16 for Shorts)."""
    from src.common.base_dto import AspectRatioEnum

    if not url:
        return AspectRatioEnum.RATIO_16_9.value
    if "/shorts/" in url:
        return AspectRatioEnum.RATIO_9_16.value
    return AspectRatioEnum.RATIO_16_9.value
