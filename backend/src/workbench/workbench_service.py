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
"""Service for workbench project and timeline management."""

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.request
from urllib.parse import urlparse

from fastapi import Depends
from google.cloud import storage

from src.common.storage_service import GcsService
from src.images.repository.media_item_repository import MediaRepository
from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.workbench.dto.workbench_dto import (
    TimelineRequest,
    TimelineCreate,
    TimelineUpdate,
    TimelineResponse,
)
from src.workbench.repository.timeline_repository import TimelineRepository

logger = logging.getLogger(__name__)


class WorkbenchService:
    def __init__(
        self,
        gcs_service: GcsService = Depends(),
        timeline_repo: TimelineRepository = Depends(),
        media_repo: MediaRepository = Depends(),
        iam_signer_credentials: IamSignerCredentials = Depends(),
    ):
        self.gcs_service = gcs_service
        self.timeline_repo = timeline_repo
        self.media_repo = media_repo
        self.iam_signer_credentials = iam_signer_credentials
        self.storage_client = storage.Client()

    async def _enrich_timeline(self, timeline: TimelineResponse):
        """Enriches a timeline with presigned URLs for video and audio clips."""
        for clip in timeline.video_clips:
            if clip.asset_ref and clip.asset_ref.type == "media_item":
                media_item_id = (
                    int(clip.asset_ref.id)
                    if str(clip.asset_ref.id).isdigit()
                    else None
                )
                if media_item_id:
                    media_item = await self.media_repo.get_by_id(media_item_id)
                    if media_item and media_item.gcs_uris:
                        gcs_uri = media_item.gcs_uris[0]
                        presigned_url = await asyncio.to_thread(
                            self.iam_signer_credentials.generate_presigned_url,
                            gcs_uri,
                        )
                        clip.presigned_url = presigned_url

                        if media_item.thumbnail_uris:
                            thumb_gcs_uri = media_item.thumbnail_uris[0]
                            presigned_thumb_url = await asyncio.to_thread(
                                self.iam_signer_credentials.generate_presigned_url,
                                thumb_gcs_uri,
                            )
                            clip.presigned_thumbnail_url = presigned_thumb_url

        for clip in timeline.audio_clips:
            if clip.asset_ref and clip.asset_ref.type == "media_item":
                media_item_id = (
                    int(clip.asset_ref.id)
                    if str(clip.asset_ref.id).isdigit()
                    else None
                )
                if media_item_id:
                    media_item = await self.media_repo.get_by_id(media_item_id)
                    if media_item and media_item.gcs_uris:
                        gcs_uri = media_item.gcs_uris[0]
                        presigned_url = await asyncio.to_thread(
                            self.iam_signer_credentials.generate_presigned_url,
                            gcs_uri,
                        )
                        clip.presigned_url = presigned_url

    async def create_timeline(
        self, timeline_create: TimelineCreate
    ) -> TimelineResponse:
        timeline = await self.timeline_repo.create_timeline(timeline_create)
        await self._enrich_timeline(timeline)
        return timeline

    async def get_timeline(self, timeline_id: int) -> TimelineResponse | None:
        timeline = await self.timeline_repo.get_by_id_with_details(timeline_id)
        if timeline:
            await self._enrich_timeline(timeline)
        return timeline

    async def list_timelines(
        self, storyboard_id: int
    ) -> list[TimelineResponse]:
        timelines = await self.timeline_repo.find_by_storyboard(storyboard_id)
        for t in timelines:
            await self._enrich_timeline(t)
        return timelines

    async def update_timeline(
        self, timeline_id: int, timeline_update: TimelineUpdate
    ) -> TimelineResponse | None:
        timeline = await self.timeline_repo.update_timeline(
            timeline_id, timeline_update
        )
        if timeline:
            await self._enrich_timeline(timeline)
        return timeline

    async def delete_timeline(self, timeline_id: int) -> bool:
        return await self.timeline_repo.delete_timeline(timeline_id)

    async def render_timeline(
        self, request: TimelineRequest
    ) -> tuple[str, str]:
        """Renders the timeline and returns (path_to_video, path_to_temp_dir).
        The caller is responsible for cleaning up the temp dir.
        """
        if not request.clips:
            raise ValueError("No clips provided")

        temp_dir = tempfile.mkdtemp(prefix="workbench_render_")
        try:
            # 1. Organize Clips
            video_clips = sorted(
                [c for c in request.clips if c.type == "video"],
                key=lambda x: x.start_time,
            )
            audio_clips = sorted(
                [c for c in request.clips if c.type == "audio"],
                key=lambda x: x.start_time,
            )

            if not video_clips:
                raise ValueError(
                    "No video clips found in timeline. At least one video clip is required.",
                )

            # 2. Download Assets (Deduplicated)
            url_to_local_path = {}
            all_unique_urls = set(c.url for c in request.clips)
            unique_urls_list = list(all_unique_urls)

            # Map URL to Input Index for FFmpeg
            url_to_input_idx = {
                url: i for i, url in enumerate(unique_urls_list)
            }

            for i, url in enumerate(unique_urls_list):
                parsed = urlparse(url)
                path_part = parsed.path
                ext = os.path.splitext(path_part)[1]
                if not ext:
                    if "wav" in url.lower():
                        ext = ".wav"
                    elif "mp3" in url.lower():
                        ext = ".mp3"
                    else:
                        ext = ".mp4"

                filename = f"asset_{i}{ext}"
                local_path = os.path.join(temp_dir, filename)
                await self._download_asset(url, local_path)
                url_to_local_path[url] = local_path

            output_path = os.path.join(temp_dir, "output.mp4")

            # 3. Inspect Media
            asset_info = {}
            for url in unique_urls_list:
                info = await self._get_media_info(url_to_local_path[url])
                asset_info[url] = {
                    "has_video": any(
                        s["codec_type"] == "video" for s in info["streams"]
                    ),
                    "has_audio": any(
                        s["codec_type"] == "audio" for s in info["streams"]
                    ),
                }

            # 4. Build FFmpeg Command
            input_args = []
            for url in unique_urls_list:
                input_args.extend(["-i", url_to_local_path[url]])

            filter_chains = []

            # --- Part A: Main Video Track (Concat) ---
            concat_v_in = []
            concat_a_in = []

            for i, clip in enumerate(video_clips):
                input_idx = url_to_input_idx[clip.url]
                info = asset_info[clip.url]

                # Video (Trim + SETPTS)
                v_label = f"[v{i}_trim]"
                if info["has_video"] and not request.hide_video:
                    filter_chains.append(
                        f"[{input_idx}:v]trim=start={clip.offset}:duration={clip.duration},setpts=PTS-STARTPTS{v_label}",
                    )
                else:
                    filter_chains.append(
                        f"color=s=1280x720:d={clip.duration}{v_label}"
                    )
                concat_v_in.append(v_label)

                # Audio (Trim + ASETPTS)
                a_label = f"[a{i}_trim]"
                # Mute video audio to allow separate audio tracks
                filter_chains.append(
                    f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=duration={clip.duration}{a_label}",
                )
                concat_a_in.append(a_label)

            # Concat the Main Track
            v_main = "[v_main]"
            a_main_raw = "[a_main_raw]"

            concat_input_str = "".join(
                [f"{v}{a}" for v, a in zip(concat_v_in, concat_a_in)],
            )
            filter_chains.append(
                f"{concat_input_str}concat=n={len(video_clips)}:v=1:a=1{v_main}{a_main_raw}",
            )

            # --- Part B: Per-Track Audio Rendering ---
            # Group audio clips by trackIndex
            audio_tracks = {}
            for clip in audio_clips:
                audio_tracks.setdefault(clip.track_index, []).append(clip)

            audio_mix_inputs = [a_main_raw]

            for track_idx, clips in audio_tracks.items():
                # Sort clips by time
                clips.sort(key=lambda x: x.start_time)

                track_segments = []
                cursor_time = 0.0

                for k, clip in enumerate(clips):
                    # 1. Gap Handling
                    gap_duration = clip.start_time - cursor_time
                    if gap_duration > 0.01:  # Small tolerance
                        gap_label = f"[track{track_idx}_gap_{k}]"
                        filter_chains.append(
                            f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=duration={gap_duration}{gap_label}",
                        )
                        track_segments.append(gap_label)

                    # 2. Clip Processing
                    input_idx = url_to_input_idx[clip.url]
                    clip_label = f"[track{track_idx}_clip_{k}]"

                    # Ensure we have stereo audio
                    # aformat=channel_layouts=stereo ensures consistency for concat
                    filter_chains.append(
                        f"[{input_idx}:a]atrim=start={clip.offset}:duration={clip.duration},asetpts=PTS-STARTPTS,aformat=channel_layouts=stereo{clip_label}",
                    )
                    track_segments.append(clip_label)

                    cursor_time = clip.start_time + clip.duration

                # 3. Concat Track Segments
                if track_segments:
                    track_label = f"[track{track_idx}_out]"
                    # concat=v=0:a=1
                    seg_str = "".join(track_segments)
                    filter_chains.append(
                        f"{seg_str}concat=n={len(track_segments)}:v=0:a=1{track_label}",
                    )
                    audio_mix_inputs.append(track_label)

            # --- Part C: Final Mix ---
            if len(audio_mix_inputs) > 1:
                # duration=first ensures the audio tracks don't extend beyond the video
                # weights could be added here if needed, but default 1/N is safer now that we have fewer inputs
                # We can use dropout_transition=0 to avoid fade-outs on stream end
                filter_chains.append(
                    f"{''.join(audio_mix_inputs)}amix=inputs={len(audio_mix_inputs)}:duration=first:dropout_transition=0[a_final]",
                )
                map_a = "[a_final]"
            else:
                map_a = a_main_raw

            # Final Command
            full_filter = ";".join(filter_chains)

            cmd = [
                "ffmpeg",
                "-y",
                *input_args,
                "-filter_complex",
                full_filter,
                "-map",
                v_main,
                "-map",
                map_a,
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-shortest",
                output_path,
            ]

            logger.info("Running FFmpeg IDs: %s", [u for u in unique_urls_list])

            process = await asyncio.to_thread(
                subprocess.run,
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            if process.returncode != 0:
                logger.error("FFmpeg failed: %s", process.stderr.decode())
                raise RuntimeError(f"FFmpeg failed: {process.stderr.decode()}")

            return output_path, temp_dir

        except Exception as e:
            logger.error("Render failed: %s", e)
            if "temp_dir" in locals() and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise e

    async def _get_media_info(self, path: str) -> dict:
        import json

        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ]
        process = await asyncio.to_thread(
            subprocess.run,
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {process.stderr.decode()}")

        return json.loads(process.stdout.decode())

    async def _download_asset(self, url: str, dest: str):
        if not url:
            raise ValueError("Empty URL")

        if url.startswith("gs://"):
            await asyncio.to_thread(self._download_gcs_blob, url, dest)
        elif url.startswith("http"):
            await asyncio.to_thread(urllib.request.urlretrieve, url, dest)
        elif url.startswith("blob:"):
            raise ValueError(
                "Cannot render local blob URLs. Please upload assets to Cloud first.",
            )
        else:
            raise ValueError(f"Unsupported URL scheme: {url}")

    def _download_gcs_blob(self, gcs_uri: str, dest: str):
        try:
            bucket_name, blob_name = gcs_uri.replace("gs://", "").split("/", 1)
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            blob.download_to_filename(dest)
        except Exception as e:
            logger.error("Failed to download GCS blob %s: %s", gcs_uri, e)
            raise e
