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
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from google.cloud.logging.handlers import CloudLoggingHandler
from google.cloud.logging import Client as LoggerClient
from urllib.parse import urlparse

from fastapi import Depends
from google.cloud import storage

from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.common.base_dto import (
    GenerationModelEnum,
    MimeTypeEnum,
    AspectRatioEnum,
)
from src.common.media_utils import generate_thumbnail
from src.common.schema.media_item_model import (
    AssetRoleEnum,
    JobStatusEnum,
    MediaItemModel,
    SourceAssetLink,
    SourceMediaItemLink,
)
from src.common.storage_service import GcsService
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.images.repository.media_item_repository import MediaRepository
from src.source_assets.repository.source_asset_repository import (
    SourceAssetRepository,
)
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


def _process_timeline_in_background(
    media_item_id: int,
    timeline_id: int,
):
    from src.database import WorkerDatabase

    worker_logger = logging.getLogger(f"timeline_worker.{media_item_id}")
    worker_logger.setLevel(logging.INFO)

    try:
        if worker_logger.hasHandlers():
            worker_logger.handlers.clear()

        if os.getenv("ENVIRONMENT") == "production":
            log_client = LoggerClient()
            handler = CloudLoggingHandler(
                log_client,
                name=f"timeline_worker.{media_item_id}",
            )
            worker_logger.addHandler(handler)
        else:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "%(asctime)s - [TIMELINE_WORKER] - %(levelname)s - %(message)s",
            )
            handler.setFormatter(formatter)
            worker_logger.addHandler(handler)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _async_worker():
            async with WorkerDatabase() as db_factory:
                async with db_factory() as db:
                    from src.workbench.repository.timeline_repository import (
                        TimelineRepository,
                    )
                    from src.workbench.workbench_service import WorkbenchService
                    from src.source_assets.repository.source_asset_repository import (
                        SourceAssetRepository,
                    )
                    from src.auth.iam_signer_credentials_service import (
                        IamSignerCredentials,
                    )
                    from types import SimpleNamespace

                    timeline_repo = TimelineRepository(db)
                    media_repo = MediaRepository(db)
                    source_asset_repo = SourceAssetRepository(db)
                    gcs_service = GcsService()
                    ffmpeg_service = FFmpegService()

                    service = WorkbenchService(
                        gcs_service=gcs_service,
                        timeline_repo=timeline_repo,
                        media_repo=media_repo,
                        source_asset_repo=source_asset_repo,
                        iam_signer_credentials=IamSignerCredentials(),
                        ffmpeg_service=ffmpeg_service,
                    )

                    try:
                        timeline = await timeline_repo.get_by_id_with_details(
                            timeline_id
                        )
                        if not timeline:
                            worker_logger.error("Timeline not found")
                            await media_repo.update(
                                media_item_id,
                                {
                                    "status": JobStatusEnum.FAILED,
                                    "error_message": "Timeline not found",
                                },
                            )
                            return

                        # Enrich timeline to get presigned URLs
                        await service._enrich_timeline(timeline)

                        output_path, temp_dir = await service._stitch_timeline(
                            timeline
                        )

                        thumbnail_path = None
                        try:
                            final_gcs_uri = await asyncio.to_thread(
                                gcs_service.upload_file_to_gcs,
                                local_path=output_path,
                                destination_blob_name=f"videos/{media_item_id}.mp4",
                                mime_type="video/mp4",
                            )

                            thumbnail_path = await asyncio.to_thread(
                                generate_thumbnail, output_path
                            )
                            thumbnail_gcs_uri = None
                            if thumbnail_path:
                                thumbnail_gcs_uri = await asyncio.to_thread(
                                    gcs_service.upload_file_to_gcs,
                                    local_path=thumbnail_path,
                                    destination_blob_name=f"thumbnails/{media_item_id}.png",
                                    mime_type="image/png",
                                )

                            update_data = {
                                "gcs_uris": (
                                    [final_gcs_uri] if final_gcs_uri else []
                                ),
                                "status": JobStatusEnum.COMPLETED,
                            }
                            if thumbnail_gcs_uri:
                                update_data["thumbnail_uris"] = [
                                    thumbnail_gcs_uri
                                ]
                            await media_repo.update(media_item_id, update_data)
                        finally:
                            if os.path.exists(temp_dir):
                                shutil.rmtree(temp_dir)
                            if thumbnail_path and os.path.exists(thumbnail_path):  # type: ignore
                                os.remove(thumbnail_path)
                    except Exception as e:
                        worker_logger.error(
                            f"Error rendering timeline: {e}", exc_info=True
                        )
                        await media_repo.update(
                            media_item_id,
                            {
                                "status": JobStatusEnum.FAILED,
                                "error_message": f"Render failed: {str(e)}",
                            },
                        )

        loop.run_until_complete(_async_worker())
        loop.close()

    except Exception as e:
        worker_logger.error(
            "Timeline generation task failed.",
            extra={"json_fields": {"media_id": media_item_id, "error": str(e)}},
            exc_info=True,
        )


class WorkbenchService:
    def __init__(
        self,
        gcs_service: GcsService = Depends(),
        timeline_repo: TimelineRepository = Depends(),
        media_repo: MediaRepository = Depends(),
        source_asset_repo: SourceAssetRepository = Depends(),
        iam_signer_credentials: IamSignerCredentials = Depends(),
        ffmpeg_service: FFmpegService = Depends(),
    ):
        self.gcs_service = gcs_service
        self.timeline_repo = timeline_repo
        self.media_repo = media_repo
        self.source_asset_repo = source_asset_repo
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
                        source_asset = await self.source_asset_repo.get_by_id(
                            source_asset_id
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
                        source_asset = await self.source_asset_repo.get_by_id(
                            source_asset_id
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

    async def render_timeline(
        self,
        timeline: TimelineResponse,
        user: UserModel,
        executor: ThreadPoolExecutor,
    ) -> MediaItemResponse | None:
        source_assets = []
        source_media_items = []

        for clip in timeline.video_clips:
            if clip.asset_ref:
                ref = clip.asset_ref
                if ref.type == "source_asset":
                    source_assets.append(
                        SourceAssetLink(
                            asset_id=(
                                int(ref.id) if str(ref.id).isdigit() else 0
                            ),
                            role=AssetRoleEnum.CONCATENATION_SOURCE,
                        )
                    )
                elif ref.type == "media_item":
                    source_media_items.append(
                        SourceMediaItemLink(
                            media_item_id=(
                                int(ref.id) if str(ref.id).isdigit() else 0
                            ),
                            media_index=0,
                            role=AssetRoleEnum.CONCATENATION_SOURCE,
                        )
                    )

        for clip in timeline.audio_clips:
            if clip.asset_ref:
                ref = clip.asset_ref
                if ref.type == "source_asset":
                    source_assets.append(
                        SourceAssetLink(
                            asset_id=(
                                int(ref.id) if str(ref.id).isdigit() else 0
                            ),
                            role=AssetRoleEnum.CONCATENATION_SOURCE,
                        )
                    )
                elif ref.type == "media_item":
                    source_media_items.append(
                        SourceMediaItemLink(
                            media_item_id=(
                                int(ref.id) if str(ref.id).isdigit() else 0
                            ),
                            media_index=0,
                            role=AssetRoleEnum.CONCATENATION_SOURCE,
                        )
                    )

        # TODO: change this to a proper way of figuring the ratio
        timeline_aspect_ratio = AspectRatioEnum.RATIO_16_9
        first_video_clip = next(
            (clip for clip in timeline.video_clips if clip.asset_ref), None
        )
        if first_video_clip and first_video_clip.asset_ref:
            ref = first_video_clip.asset_ref
            item_id = int(ref.id) if str(ref.id).isdigit() else None
            if item_id:
                if ref.type == "media_item":
                    media_item = await self.media_repo.get_by_id(item_id)
                    if media_item and media_item.aspect_ratio:
                        timeline_aspect_ratio = media_item.aspect_ratio
                elif ref.type == "source_asset":
                    source_asset = await self.source_asset_repo.get_by_id(
                        item_id
                    )
                    if source_asset and source_asset.aspect_ratio:
                        timeline_aspect_ratio = source_asset.aspect_ratio

        ws_id = (
            int(timeline.workspace_id)
            if str(timeline.workspace_id).isdigit()
            else 1
        )

        new_media_item = MediaItemModel(
            prompt=f"Render of timeline {timeline.timeline_id}",
            mime_type=MimeTypeEnum.VIDEO_MP4,
            status=JobStatusEnum.PROCESSING,
            user_id=user.id,
            user_email=user.email,
            workspace_id=ws_id,
            model=GenerationModelEnum.WORKBENCH_RENDER,
            aspect_ratio=timeline_aspect_ratio,
            gcs_uris=[],
            num_media=1,
            source_assets=source_assets,
            source_media_items=source_media_items,
        )
        db_item = await self.media_repo.create(new_media_item)

        executor.submit(
            _process_timeline_in_background,
            db_item.id,
            int(timeline.timeline_id),
        )

        return MediaItemResponse.model_validate(db_item)

    async def render_timeline_legacy(
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
