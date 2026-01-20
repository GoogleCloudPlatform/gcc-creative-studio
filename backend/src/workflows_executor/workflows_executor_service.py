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

import logging
import os
import asyncio

from typing import Annotated, Optional, Union, List, Dict, Any

from fastapi import Header, HTTPException
from google import genai
from google.genai import types
from httpx import AsyncClient as RestClient
from src.common.schema.genai_model_setup import GenAIModelSetup
from src.common.schema.media_item_model import AssetRoleEnum
from src.workflows_executor.dto.workflows_executor_dto import (
    GenerateTextRequest,
    GenerateImageRequest,
    EditImageRequest,
    GenerateVideoRequest,
    CropImageRequest,
    VirtualTryOnRequest,
    GenerateAudioRequest,
)
from src.workflows.schema.workflow_model import ReferenceImage
from src.config.config_service import config_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WorkflowsExecutorService:
    def __init__(self):
        self.backend_url = config_service.BACKEND_URL
        self.rest_client = RestClient(timeout=300)
        self.genai_client = GenAIModelSetup.init()

    def _normalize_asset_inputs(
        self, inputs, default_role: AssetRoleEnum = AssetRoleEnum.INPUT
    ):
        """
        Normalizes mixed input types (int, list, ReferenceImage) into
        structured media items and asset IDs.
        """
        media_items = []
        asset_ids = []

        # Wrap single items in a list for uniform processing
        raw_list = inputs if isinstance(inputs, list) else [inputs] if inputs is not None else []

        # Helper to flatten nested lists
        def flatten(items):
            for x in items:
                if isinstance(x, list):
                    yield from flatten(x)
                else:
                    yield x

        for item in flatten(raw_list):
            if isinstance(item, int):
                media_items.append(
                    {
                        "media_item_id": item,
                        "media_index": 0,
                        "role": default_role.value,
                    }
                )
            elif isinstance(item, ReferenceImage):
                if item.sourceMediaItem:
                    media_items.append(
                        {
                            "media_item_id": item.sourceMediaItem.mediaItemId,
                            "media_index": item.sourceMediaItem.mediaIndex,
                            "role": item.sourceMediaItem.role
                            or default_role.value,
                        }
                    )
                elif item.sourceAssetId:
                    asset_ids.append(item.sourceAssetId)
        return media_items, asset_ids

    async def _poll_job_status(self, media_id: int, authorization: str | None = None):
        """
        Polls the gallery endpoint until the job is completed or failed.
        """

        url = f"{self.backend_url}/api/gallery/item/{media_id}"
        headers = {"Authorization": authorization} if authorization else {}

        # Poll configuration
        initial_delay = 2
        poll_interval = 5
        timeout = 300  # 5 minutes timeout

        await asyncio.sleep(initial_delay)

        start_time = asyncio.get_event_loop().time()

        while True:
            current_time = asyncio.get_event_loop().time()
            if current_time - start_time > timeout:
                raise HTTPException(status_code=504, detail="Image generation timed out")

            try:
                response = await self.rest_client.get(url, headers=headers)
                if response.status_code != 200:
                    logger.warning(f"Polling failed with status {response.status_code}: {response.text}")
                    raise HTTPException(status_code=response.status_code, detail=f"Polling error: {response.text}")
                else:
                    data = response.json()
                    status = data.get("status")

                    if status == "completed":
                        return True
                    elif status == "failed":
                        error_message = data.get("error_message") or data.get("errorMessage") or "Unknown error"
                        raise HTTPException(status_code=500, detail=f"Image generation failed: {error_message}")
            except Exception as e:
                if isinstance(e, HTTPException):
                    raise e
                logger.error(f"Error during polling: {e}")
                # Continue polling? Or fail?
                # If we can't check status, we might be blind.

            await asyncio.sleep(poll_interval)

    async def _resolve_media_to_parts(self, inputs, authorization: str | None = None) -> List[types.Part]:
        """
        Resolves mixed input types into a list of Gemini types.Part.
        """
        parts = []
        media_items, asset_ids = self._normalize_asset_inputs(inputs)

        headers = {"Authorization": authorization} if authorization else {}

        # Resolve Media Items
        for item in media_items:
            media_id = item["media_item_id"]
            index = item["media_index"]
            try:
                url = f"{self.backend_url}/api/gallery/item/{media_id}"
                response = await self.rest_client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    gcs_uris = data.get("gcsUris") or data.get("gcs_uris") or []
                    mime_type = data.get("mimeType") or data.get("mime_type") or "image/png"
                    if 0 <= index < len(gcs_uris):
                        uri = gcs_uris[index]
                        logger.info(f"Adding part from URI: {uri}, mime_type: {mime_type}")
                        parts.append(types.Part.from_uri(file_uri=uri, mime_type=mime_type))
                    else:
                        logger.warning(f"Index {index} out of range for gcs_uris: {gcs_uris}")
                else:
                    logger.warning(f"Failed to fetch gallery item {media_id}: {response.text}")
            except Exception as e:
                logger.error(f"Error resolving media item {media_id}: {e}")

        # Resolve Source Assets
        for asset_id in asset_ids:
            logger.info(f"Resolving source asset {asset_id}")
            try:
                url = f"{self.backend_url}/api/source_assets/{asset_id}"
                response = await self.rest_client.get(url, headers=headers)
                logger.info(f"Source asset status: {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    gcs_uri = data.get("gcsUri") or data.get("gcs_uri")
                    mime_type = data.get("mimeType") or data.get("mime_type") or "image/jpeg"
                    if gcs_uri:
                        logger.info(f"Adding part from URI: {gcs_uri}")
                        parts.append(types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type))
            except Exception as e:
                logger.error(f"Error resolving source asset {asset_id}: {e}")
        logger.info(f"Resolved media parts: {parts}")
        return parts

    async def generate_text(self, request: GenerateTextRequest, authorization: str | None = None):
        logger.info(f"authorization: {authorization}")
        generate_content_config = types.GenerateContentConfig(
            temperature=request.config.temperature,
            top_p=0.95,
            max_output_tokens=65535,
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
            ],
        )

        contents = []

        logger.info(f"generate_text inputs: {request.inputs}")
        # 1. Add Text Prompt
        if isinstance(request.inputs.prompt, str):
            contents.append(types.Part.from_text(text=request.inputs.prompt))

        # 2. Add Images
        if request.inputs.input_images:
            logger.info("Adding images")
            image_parts = await self._resolve_media_to_parts(request.inputs.input_images, authorization)
            logger.info(f"Image parts: {image_parts}")
            contents.extend(image_parts)

        # 3. Add Videos
        if request.inputs.input_videos:
            video_parts = await self._resolve_media_to_parts(request.inputs.input_videos, authorization)
            contents.extend(video_parts)

        text = ""
        # Note: The original code used a stream but returned the full text at the end.
        # Keeping this behavior for now.
        for chunk in self.genai_client.models.generate_content_stream(
            model=request.config.model,
            contents=contents,
            config=generate_content_config,
        ):
            if chunk.text:
                text += chunk.text
        return {"generated_text": text}

    async def generate_image(self, request: GenerateImageRequest, authorization: str | None = None):
        logger.info(f"Generate image execution")

        url = self.backend_url + "/api/images/generate-images"

        body = {
            "prompt": request.inputs.prompt,
            "workspace_id": request.workspace_id,
            "generation_model": request.config.model,
            "aspect_ratio": request.config.aspect_ratio,
            "use_brand_guidelines": request.config.brand_guidelines,
            "number_of_media": 1,
        }

        headers = {"Authorization": authorization} if authorization else {}

        logger.info(
            f"Call backend with url: {url}, body: {body}, headers: {headers}"
        )

        response = await self.rest_client.post(url, json=body, headers=headers)

        if response.status_code != 200:
            logger.error(f"Backend error: {response.text}")
            raise HTTPException(status_code=response.status_code, detail=f"Backend error: {response.text}")

        dict_response = response.json()
        image_id = dict_response.get("id", None)
        if not image_id:
            raise HTTPException(status_code=500, detail="Couldn't create image")

        # Poll for completion
        await self._poll_job_status(image_id, authorization)

        return {"generated_image": image_id}

    async def edit_image(self, request: EditImageRequest, authorization: str | None = None):
        logger.info(f"Edit image execution")

        url = self.backend_url + "/api/images/generate-images"

        media_items, asset_ids = self._normalize_asset_inputs(request.inputs.input_images)

        body = {
            "prompt": request.inputs.prompt,
            "workspace_id": request.workspace_id,
            "generation_model": request.config.model,
            "aspect_ratio": request.config.aspect_ratio,
            "use_brand_guidelines": request.config.brand_guidelines,
            "number_of_media": 1,
            "source_media_items": media_items,
            "source_asset_ids": asset_ids,
        }

        headers = {"Authorization": authorization} if authorization else {}

        logger.info(
            f"Call backend with url: {url}, body: {body}, headers: {headers}"
        )

        response = await self.rest_client.post(url, json=body, headers=headers)

        if response.status_code != 200:
            logger.error(f"Backend error: {response.text}")
            raise HTTPException(status_code=response.status_code, detail=f"Backend error: {response.text}")

        dict_response = response.json()
        image_id = dict_response.get("id", None)
        if not image_id:
            raise HTTPException(status_code=500, detail="Couldn't edit image")

        # Poll for completion
        await self._poll_job_status(image_id, authorization)

        return {"edited_image": image_id}

    async def generate_video(self, request: GenerateVideoRequest, authorization: str | None = None):
        logger.info(f"Generate video execution")

        url = self.backend_url + "/api/videos/generate-videos"

        # 1. Process main reference images
        media_items, asset_ids = self._normalize_asset_inputs(
            request.inputs.input_images,
            default_role=AssetRoleEnum.IMAGE_REFERENCE_ASSET,
        )

        reference_images = []
        for aid in asset_ids:
            reference_images.append({"asset_id": aid, "reference_type": "ASSET"})

        # 2. Process Start Frame
        start_media, start_assets = self._normalize_asset_inputs(
            request.inputs.start_frame, default_role=AssetRoleEnum.START_FRAME
        )
        media_items.extend(start_media)
        start_image_asset_id = start_assets[0] if start_assets else None

        # 3. Process End Frame
        end_media, end_assets = self._normalize_asset_inputs(
            request.inputs.end_frame, default_role=AssetRoleEnum.END_FRAME
        )
        media_items.extend(end_media)
        end_image_asset_id = end_assets[0] if end_assets else None

        body = {
            "prompt": request.inputs.prompt,
            "workspace_id": request.workspace_id,
            "generation_model": request.config.model,
            "use_brand_guidelines": request.config.brand_guidelines,
            "reference_images": reference_images,
            "source_media_items": media_items,
            "start_image_asset_id": start_image_asset_id,
            "end_image_asset_id": end_image_asset_id,
            "number_of_media": 1,
        }

        headers = {"Authorization": authorization} if authorization else {}

        logger.info(
            f"Call backend with url: {url}, body: {body}, headers: {headers}"
        )

        response = await self.rest_client.post(url, json=body, headers=headers)

        if response.status_code != 200:
            logger.error(f"Backend error: {response.text}")
            raise HTTPException(status_code=response.status_code, detail=f"Backend error: {response.text}")

        dict_response = response.json()
        video_id = dict_response.get("id", None)
        if not video_id:
            raise HTTPException(status_code=500, detail="Couldn't create video")

        # Poll for completion
        await self._poll_job_status(video_id, authorization)

        return {"generated_video": video_id}

    async def crop_image(self, request: CropImageRequest):
        # logic here
        return {"cropped_image": "https://example.com/cropped_image.png"}

    def _map_to_vto_input_link(self, input_data: int | list | ReferenceImage) -> Optional[dict]:
        if not input_data:
            return None

        # If input is a list, take the first element
        if isinstance(input_data, list):
            if len(input_data) == 0:
                return None
            input_data = input_data[0]

        # Handle ReferenceImage
        if isinstance(input_data, ReferenceImage):
            if input_data.sourceMediaItem:
                return {
                    "source_media_item": {
                        "media_item_id": input_data.sourceMediaItem.mediaItemId,
                        "media_index": input_data.sourceMediaItem.mediaIndex,
                    }
                }
            elif input_data.sourceAssetId:
                return {"source_asset_id": input_data.sourceAssetId}

        if isinstance(input_data, int):
            return {
                "source_media_item": {
                    "media_item_id": input_data,
                    "media_index": 0,
                }
            }

        return None

    async def virtual_try_on(self, request: VirtualTryOnRequest, authorization: str | None = None):
        logger.info(f"Virtual Try On execution")

        url = self.backend_url + "/api/images/generate-images-for-vto"

        # Map inputs
        person_image = self._map_to_vto_input_link(request.inputs.model_image) # type: ignore
        top_image = self._map_to_vto_input_link(request.inputs.top_image) # type: ignore
        bottom_image = self._map_to_vto_input_link(request.inputs.bottom_image) # type: ignore
        dress_image = self._map_to_vto_input_link(request.inputs.dress_image) # type: ignore
        shoes_image = self._map_to_vto_input_link(request.inputs.shoes_image) # type: ignore

        # Ensure person_image is present (it's required in VtoDto)
        if not person_image:
            raise HTTPException(status_code=400, detail="Person image is required for Virtual Try-On")

        body = {
            "workspace_id": request.workspace_id,
            "number_of_media": 1, # Default to 1 as per other methods or config? VtoDto defaults to 1.
            "person_image": person_image,
            "top_image": top_image,
            "bottom_image": bottom_image,
            "dress_image": dress_image,
            "shoe_image": shoes_image,
        }

        headers = {"Authorization": authorization} if authorization else {}

        logger.info(
            f"Call backend with url: {url}, body: {body}, headers: {headers}"
        )

        response = await self.rest_client.post(url, json=body, headers=headers)

        if response.status_code != 200:
            logger.error(f"Backend error: {response.text}")
            raise HTTPException(status_code=response.status_code, detail=f"Backend error: {response.text}")

        dict_response = response.json()
        image_id = dict_response.get("id", None)
        if not image_id:
            raise HTTPException(status_code=500, detail="Couldn't create VTO image")

        # Poll for completion
        await self._poll_job_status(image_id, authorization)

        return {"generated_image": image_id}

    async def generate_audio(self, request: GenerateAudioRequest, authorization: str | None = None):
        logger.info(f"Generate audio execution")

        url = self.backend_url + "/api/audios/generate"

        body = {
            "workspace_id": request.workspace_id,
            "prompt": request.inputs.prompt,
            "model": request.config.model,
            "voice_name": request.config.voice_name,
            "language_code": request.config.language_code,
            "negative_prompt": request.config.negative_prompt,
            "seed": request.config.seed,
        }

        # Filter None values to let DTO defaults take over if needed
        body = {k: v for k, v in body.items() if v is not None}

        headers = {"Authorization": authorization} if authorization else {}

        logger.info(
            f"Call backend with url: {url}, body: {body}, headers: {headers}"
        )

        # Note: Audio generation is synchronous in the current controller/service implementation
        response = await self.rest_client.post(url, json=body, headers=headers)

        if response.status_code != 200:
            logger.error(f"Backend error: {response.text}")
            raise HTTPException(status_code=response.status_code, detail=f"Backend error: {response.text}")

        dict_response = response.json()
        audio_id = dict_response.get("id", None)

        if not audio_id:
            raise HTTPException(status_code=500, detail="Couldn't create audio")

        # Poll for completion
        await self._poll_job_status(audio_id, authorization)

        return {"generated_audio": audio_id}
