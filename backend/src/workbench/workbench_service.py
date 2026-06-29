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
import gc
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.request
from urllib.parse import urlparse

from fastapi import Depends
from google.cloud import storage

from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.common.storage_service import GcsService
from src.images.repository.media_item_repository import MediaRepository
from src.source_assets.source_asset_service import SourceAssetService
from src.users.user_model import UserModel
from src.workbench.dto.workbench_dto import (
    AudioClip,
    RenderTimelineResponse,
    TimelineCreate,
    TimelineRequest,
    TimelineResponse,
    TimelineUpdate,
    VideoClip,
    VideoTimeline,
)
from src.workbench.ffmpeg_service import FFmpegService
from src.workbench.repository.timeline_repository import TimelineRepository

logger = logging.getLogger(__name__)


class WorkbenchService:
    def __init__(
        self,
        gcs_service: GcsService = Depends(),
        timeline_repo: TimelineRepository = Depends(),
        media_repo: MediaRepository = Depends(),
        source_asset_service: SourceAssetService = Depends(),
        iam_signer_credentials: IamSignerCredentials = Depends(),
        ffmpeg_service: FFmpegService = Depends(),
    ):
        self.gcs_service = gcs_service
        self.timeline_repo = timeline_repo
        self.media_repo = media_repo
        self.source_asset_service = source_asset_service
        self.iam_signer_credentials = iam_signer_credentials
        self.ffmpeg_service = ffmpeg_service
        self.storage_client = storage.Client()

    async def _enrich_timeline(self, timeline: TimelineResponse):
        """Enriches a timeline with presigned URLs for video and audio clips."""
        for clip in timeline.video_clips:
            if clip.asset_ref:
                gcs_uri = None
                thumb_gcs_uri = None
                if clip.asset_ref.type == "media_item":
                    media_item_id = (
                        int(clip.asset_ref.id)
                        if str(clip.asset_ref.id).isdigit()
                        else None
                    )
                    if media_item_id:
                        media_item = await self.media_repo.get_by_id(
                            media_item_id
                        )
                        if media_item and media_item.gcs_uris:
                            gcs_uri = media_item.gcs_uris[0]
                            if media_item.thumbnail_uris:
                                thumb_gcs_uri = media_item.thumbnail_uris[0]
                elif clip.asset_ref.type == "source_asset":
                    source_asset_id = (
                        int(clip.asset_ref.id)
                        if str(clip.asset_ref.id).isdigit()
                        else None
                    )
                    if source_asset_id:
                        source_asset = (
                            await self.source_asset_service.repo.get_by_id(
                                source_asset_id
                            )
                        )
                        if source_asset and source_asset.gcs_uri:
                            gcs_uri = source_asset.gcs_uri
                            thumb_gcs_uri = source_asset.thumbnail_gcs_uri

                if gcs_uri:
                    presigned_url = await asyncio.to_thread(
                        self.iam_signer_credentials.generate_presigned_url,
                        gcs_uri,
                    )
                    clip.presigned_url = presigned_url
                if thumb_gcs_uri:
                    presigned_thumb_url = await asyncio.to_thread(
                        self.iam_signer_credentials.generate_presigned_url,
                        thumb_gcs_uri,
                    )
                    clip.presigned_thumbnail_url = presigned_thumb_url

        for clip in timeline.audio_clips:
            if clip.asset_ref:
                gcs_uri = None
                if clip.asset_ref.type == "media_item":
                    media_item_id = (
                        int(clip.asset_ref.id)
                        if str(clip.asset_ref.id).isdigit()
                        else None
                    )
                    if media_item_id:
                        media_item = await self.media_repo.get_by_id(
                            media_item_id
                        )
                        if media_item and media_item.gcs_uris:
                            gcs_uri = media_item.gcs_uris[0]
                elif clip.asset_ref.type == "source_asset":
                    source_asset_id = (
                        int(clip.asset_ref.id)
                        if str(clip.asset_ref.id).isdigit()
                        else None
                    )
                    if source_asset_id:
                        source_asset = (
                            await self.source_asset_service.repo.get_by_id(
                                source_asset_id
                            )
                        )
                        if source_asset and source_asset.gcs_uri:
                            gcs_uri = source_asset.gcs_uri

                if gcs_uri:
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

    async def render_timeline_by_id(
        self, timeline_id: int, user: UserModel
    ) -> RenderTimelineResponse | None:
        timeline = await self.get_timeline(timeline_id)
        if not timeline:
            return None

        output_path, temp_dir = await self._stitch_timeline(timeline)
        try:
            with open(output_path, "rb") as f:
                file_bytes = f.read()

            ws_id = (
                int(timeline.workspace_id)
                if str(timeline.workspace_id).isdigit()
                else 1
            )
            filename = f"timeline_{timeline_id}_export.mp4"

            source_asset = await self.source_asset_service.upload_asset(
                user=user,
                file_bytes=file_bytes,
                filename=filename,
                workspace_id=ws_id,
                mime_type="video/mp4",
                skip_deduplication=True,
            )

            return RenderTimelineResponse(
                asset_id=source_asset.id,
                gcs_uri=source_asset.gcs_uri,
                timeline_id=timeline_id,
                message="Timeline rendered and saved as Source Asset successfully",
            )
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    async def render_timeline(
        self, request: TimelineRequest
    ) -> tuple[str, str]:
        """Legacy render method for backwards compatibility."""
        if not request.clips:
            raise ValueError("No clips provided")

        temp_dir = tempfile.mkdtemp(prefix="workbench_render_")
        try:
            video_clips = sorted(
                [c for c in request.clips if c.type == "video"],
                key=lambda x: x.start_time,
            )
            audio_clips = sorted(
                [c for c in request.clips if c.type == "audio"],
                key=lambda x: x.start_time,
            )
            if not video_clips:
                raise ValueError("No video clips found in timeline.")

            url_to_local_path = {}
            all_unique_urls = set(c.url for c in request.clips)
            unique_urls_list = list(all_unique_urls)
            url_to_input_idx = {
                url: i for i, url in enumerate(unique_urls_list)
            }

            for i, url in enumerate(unique_urls_list):
                ext = ".mp4"
                filename = f"asset_{i}{ext}"
                local_path = os.path.join(temp_dir, filename)
                await self._download_asset(url, local_path)
                url_to_local_path[url] = local_path

            output_path = os.path.join(temp_dir, "output.mp4")
            asset_info = {}
            for url in unique_urls_list:
                info = await self.ffmpeg_service.get_media_info(
                    url_to_local_path[url]
                )
                asset_info[url] = {
                    "has_video": any(
                        s["codec_type"] == "video" for s in info["streams"]
                    ),
                    "has_audio": any(
                        s["codec_type"] == "audio" for s in info["streams"]
                    ),
                }

            input_args = []
            for url in unique_urls_list:
                input_args.extend(["-i", url_to_local_path[url]])

            filter_chains = []
            concat_v_in = []
            concat_a_in = []

            for i, clip in enumerate(video_clips):
                input_idx = url_to_input_idx[clip.url]
                info = asset_info[clip.url]
                v_label = f"[v{i}_trim]"
                if info["has_video"] and not request.hide_video:
                    filter_chains.append(
                        f"[{input_idx}:v]trim=start={clip.offset}:duration={clip.duration},setpts=PTS-STARTPTS{v_label}"
                    )
                else:
                    filter_chains.append(
                        f"color=s=1280x720:d={clip.duration}{v_label}"
                    )
                concat_v_in.append(v_label)

                a_label = f"[a{i}_trim]"
                filter_chains.append(
                    f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=duration={clip.duration}{a_label}"
                )
                concat_a_in.append(a_label)

            v_main = "[v_main]"
            a_main_raw = "[a_main_raw]"
            concat_input_str = "".join(
                [f"{v}{a}" for v, a in zip(concat_v_in, concat_a_in)]
            )
            filter_chains.append(
                f"{concat_input_str}concat=n={len(video_clips)}:v=1:a=1{v_main}{a_main_raw}"
            )

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
                a_main_raw,
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-shortest",
                output_path,
            ]
            process = await asyncio.to_thread(
                subprocess.run,
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if process.returncode != 0:
                raise RuntimeError(f"FFmpeg failed: {process.stderr.decode()}")

            return output_path, temp_dir
        except Exception as e:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise e

    async def _stitch_timeline(
        self, timeline: VideoTimeline
    ) -> tuple[str, str]:
        """Stitches a VideoTimeline object using FFmpeg and returns (output_path, temp_dir)."""
        return await self.ffmpeg_service.stitch_timeline(
            timeline, self._download_asset
        )

    async def _download_asset(self, url: str, dest: str):
        if not url:
            raise ValueError("Empty URL")
        if url.startswith("gs://"):
            await asyncio.to_thread(self._download_gcs_blob, url, dest)
        elif url.startswith("http"):
            await asyncio.to_thread(urllib.request.urlretrieve, url, dest)
        elif url.startswith("blob:"):
            raise ValueError("Cannot render local blob URLs.")
        else:
            raise ValueError(f"Unsupported URL scheme: {url}")

    def _download_gcs_blob(self, gcs_uri: str, dest: str):
        try:
            bucket_name, blob_name = gcs_uri.replace("gs://", "").split("/", 1)
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            blob.download_to_filename(dest)
        except Exception as e:
            logger.error(f"Failed to download GCS blob {gcs_uri}: {e}")
            raise e
