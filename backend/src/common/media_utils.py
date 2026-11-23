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
import tempfile
from urllib.parse import parse_qs, urlparse

from PIL import Image as PILImage
from PIL import ImageOps

from src.common.base_dto import AspectRatioEnum
from src.common.storage_service import GcsService

logger = logging.getLogger(__name__)


VIDEO_THUMBNAIL_MIME_TYPE = "image/jpeg"
VIDEO_THUMBNAIL_EXT = ".jpg"


def _derive_thumbnail_blob_name(gcs_uri: str, ext: str) -> str | None:
    """Returns derived *_thumbnail<ext> blob path for a valid gs:// URI."""
    if not gcs_uri or not gcs_uri.startswith("gs://"):
        return None
    parts = gcs_uri.split("/", 3)  # gs:, , bucket, blob_name
    if len(parts) < 4 or not parts[3]:
        return None
    path = pathlib.Path(parts[3])
    thumb_name = f"{path.stem}_thumbnail{ext}"
    if path.parent == pathlib.Path():
        return thumb_name
    return str(path.parent / thumb_name)


def generate_image_thumbnail_bytes(image_bytes: bytes) -> bytes | None:
    """Generates a 512px max-edge compressed WebP thumbnail from image bytes."""
    try:
        with PILImage.open(io.BytesIO(image_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            has_alpha = img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            )
            target_mode = "RGBA" if has_alpha else "RGB"
            if img.mode != target_mode:
                img = img.convert(target_mode)

            img.thumbnail((512, 512), PILImage.Resampling.LANCZOS)
            output = io.BytesIO()
            img.save(output, format="WEBP", quality=80, method=4)
            return output.getvalue()
    except Exception as e:
        logger.error("Error generating image thumbnail: %s", e)
        return None


def generate_image_thumbnail_from_gcs(
    gcs_service: GcsService,
    gcs_uri: str,
) -> str | None:
    """Generates a WebP thumbnail for the given GCS image URI and uploads it."""
    try:
        new_blob_name = _derive_thumbnail_blob_name(gcs_uri, ".webp")
        if not new_blob_name:
            return None

        image_bytes = gcs_service.download_bytes_from_gcs(gcs_uri)
        if not image_bytes:
            return None

        thumbnail_bytes = generate_image_thumbnail_bytes(image_bytes)
        if not thumbnail_bytes:
            return None

        return gcs_service.upload_bytes_to_gcs(
            thumbnail_bytes,
            new_blob_name,
            "image/webp",
        )

    except Exception as e:
        logger.error("Thumbnail generation failed: %s", e)
        return None


def generate_thumbnail(video_path: str) -> str | None:
    """Generates a 512px-capped JPEG thumbnail from a video file using ffmpeg.

    Args:
        video_path: The path to the video file.

    Returns:
        The path to the generated JPEG thumbnail, or None if it fails.

    """
    if not video_path:
        return None

    thumbnail_filename = (
        "thumbnail_"
        + os.path.splitext(os.path.basename(video_path))[0]
        + ".jpg"
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
        "-vf",
        "scale='if(gt(iw,ih),min(512,iw),-2)':'if(gt(iw,ih),-2,min(512,ih))'",
        "-q:v",
        "4",
        "-y",  # Overwrite output file if it exists
        thumbnail_path,
    ]
    try:
        subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=30
        )
        return thumbnail_path
    except subprocess.TimeoutExpired:
        logger.error(
            "Timed out generating video thumbnail for %s after 30s.",
            video_path,
        )
        return None
    except FileNotFoundError:
        logger.error(
            "ffmpeg not found. Please ensure ffmpeg is installed and in "
            "your PATH.",
        )
        return None
    except subprocess.CalledProcessError as e:
        logger.error("Error generating thumbnail: %s", e.stderr)
        return None


def generate_video_thumbnail_from_gcs(
    gcs_service: GcsService,
    gcs_uri: str,
) -> str | None:
    """Streams GCS video to temp disk, builds a JPEG thumbnail, and uploads."""
    try:
        new_blob_name = _derive_thumbnail_blob_name(
            gcs_uri, VIDEO_THUMBNAIL_EXT
        )
        if not new_blob_name:
            return None

        blob_path = pathlib.Path(gcs_uri.split("/", 3)[3])
        suffix = blob_path.suffix or ".mp4"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_video_path = os.path.join(temp_dir, f"video{suffix}")
            bytes_written = 0
            with open(temp_video_path, "wb") as video_file:
                for chunk in (
                    gcs_service.download_stream_from_gcs(gcs_uri) or ()
                ):
                    if chunk:
                        video_file.write(chunk)
                        bytes_written += len(chunk)
            if bytes_written == 0:
                return None

            thumbnail_path = generate_thumbnail(temp_video_path)
            if (
                not thumbnail_path
                or not os.path.exists(thumbnail_path)
                or os.path.getsize(thumbnail_path) == 0
            ):
                return None

            return gcs_service.upload_file_to_gcs(
                local_path=thumbnail_path,
                destination_blob_name=new_blob_name,
                mime_type=VIDEO_THUMBNAIL_MIME_TYPE,
            )
    except Exception as e:
        logger.error("Video thumbnail generation failed: %s", e)
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
        parsed = urlparse(trimmed)
        hostname = parsed.hostname.lower() if parsed.hostname else ""

        is_youtube = any(
            hostname == h or hostname.endswith("." + h)
            for h in ("youtube.com", "youtube-nocookie.com")
        )
        is_short = hostname == "youtu.be" or hostname.endswith(".youtu.be")

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
    if "youtube" in trimmed or "youtu.be" in trimmed:
        pattern = r"(?:youtu\.be\/|v\/|u\/\w\/|embed\/|shorts\/|watch\?v=|&v=)([a-zA-Z0-9_-]{11})"
        match = re.search(pattern, trimmed)
        return match.group(1) if match else None
    return None


def get_youtube_aspect_ratio(url: str | None) -> str:
    """Determines YouTube aspect ratio from URL (9:16 for Shorts)."""
    if not url:
        return AspectRatioEnum.RATIO_16_9.value
    if "/shorts/" in url:
        return AspectRatioEnum.RATIO_9_16.value
    return AspectRatioEnum.RATIO_16_9.value


def format_api_error_message(e: Exception | str | None) -> str:
    """Extracts the exact, human-readable error message from API exceptions or error strings,
    handling Google GenAI, Vertex AI, and Gemini Omni error payloads.
    """
    if e is None:
        return "Unknown error occurred during media generation."

    err_str = str(e)

    # 1. Try regex extraction for 'message': "..." or 'message': '...' inside API error payloads
    msg_match = re.search(r"['\"]message['\"]:\s*\"([^\"]+)\"", err_str)
    if not msg_match:
        msg_match = re.search(r"['\"]message['\"]:\s*'([^']+)'", err_str)

    if msg_match:
        return msg_match.group(1).strip()

    # 2. Try parsing string as JSON if it contains a JSON-like object
    if "{" in err_str and "}" in err_str:
        try:
            start_idx = err_str.index("{")
            end_idx = err_str.rindex("}") + 1
            json_substr = err_str[start_idx:end_idx].replace("'", '"')
            parsed = json.loads(json_substr)
            if isinstance(parsed, dict):
                if (
                    "error" in parsed
                    and isinstance(parsed["error"], dict)
                    and "message" in parsed["error"]
                ):
                    return str(parsed["error"]["message"])
                if "message" in parsed:
                    return str(parsed["message"])
        except Exception:
            pass

    return err_str
