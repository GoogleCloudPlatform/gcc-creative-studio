# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may
# obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Gemini Service for multimodal content generation."""

import asyncio
import json
import logging
from enum import Enum
from typing import Any

from fastapi import Depends, HTTPException
from google.genai import Client, types
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.brand_guidelines.dto.brand_guideline_search_dto import (
    BrandGuidelineSearchDto,
)
from src.brand_guidelines.repository.brand_guideline_repository import (
    BrandGuidelineRepository,
)
from src.brand_guidelines.schema.brand_guideline_model import (
    BrandGuidelineModel,
)
from src.common.base_dto import GenerationModelEnum
from src.common.retry import is_transient_or_quota
from src.config.config_service import config_service
from src.audios.dto.create_audio_dto import CreateAudioDto
from src.images.dto.create_imagen_dto import CreateImagenDto
from src.multimodal.dto.create_prompt_imagen_dto import CreatePromptImageDto
from src.multimodal.dto.create_prompt_video_dto import CreatePromptVideoDto
from src.multimodal.dto.gemini_prompt_enhancer_dto import (
    GenerateAudioMediaMetadataResponseDto,
    GenerateMediaMetadataResponseDto,
    MusicalProfileDto,
    PromptTargetEnum,
)
from src.multimodal.rewriters import (
    ITERATE_AUDIO_TEXT_PROMPT_TEMPLATE,
    RANDOM_AUDIO_PROMPT_TEMPLATE,
    RANDOM_IMAGE_PROMPT_TEMPLATE,
    RANDOM_VIDEO_PROMPT_TEMPLATE,
    REWRITE_AUDIO_TEXT_PROMPT_TEMPLATE,
    REWRITE_IMAGE_JSON_PROMPT_TEMPLATE,
    REWRITE_IMAGE_TEXT_PROMPT_TEMPLATE,
    REWRITE_VIDEO_JSON_PROMPT_TEMPLATE,
    REWRITE_VIDEO_TEXT_PROMPT_TEMPLATE,
)
from src.multimodal.schema.gemini_model_setup import GeminiModelSetup
from src.videos.dto.create_veo_dto import CreateVeoDto
from src.images.repository.media_item_repository import MediaRepository
from src.source_assets.repository.source_asset_repository import (
    SourceAssetRepository,
)
from src.multimodal.dto.multimodal_generation_request_dto import (
    MultimodalGenerationRequestDto,
)

logger = logging.getLogger(__name__)


class ResponseMimeTypeEnum(str, Enum):
    JSON = "application/json"
    TEXT = "text/plain"


class GeminiService:
    """A dedicated service for interactions with Google's Gemini models.
    Handles client initialization, prompt rewriting, and error handling.
    """

    def __init__(
        self,
        brand_guideline_repo: BrandGuidelineRepository = Depends(),
        media_item_repo: MediaRepository = Depends(),
        source_asset_repo: SourceAssetRepository = Depends(),
    ):
        """Initializes the Gemini client and configuration."""
        self.client: Client = GeminiModelSetup.init()
        self.cfg = config_service
        self.rewriter_model = self.cfg.GEMINI_MODEL_ID
        self.brand_guideline_repo = brand_guideline_repo
        self.media_item_repo = media_item_repo
        self.source_asset_repo = source_asset_repo

    def _get_response_schema(self, target: PromptTargetEnum) -> type[BaseModel]:
        """Dynamically gets the Pydantic schema based on the target type."""
        if target is PromptTargetEnum.IMAGE:
            return CreatePromptImageDto
        if target is PromptTargetEnum.VIDEO:
            return CreatePromptVideoDto
        raise ValueError(f"No response schema defined for target: {target}")

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        # Only quota / 503 / network errors (Q10); never safety or 4xx.
        retry=retry_if_exception(is_transient_or_quota),
        reraise=True,
    )
    def generate_structured_prompt(
        self,
        original_prompt: str,
        target_type: PromptTargetEnum,
        prompt_template: str,
        response_mime_type: ResponseMimeTypeEnum = ResponseMimeTypeEnum.JSON,
        response_schema: type[BaseModel] | None = None,
        extra_parts: list[types.Part] | None = None,
    ) -> str:
        """Rewrites a user prompt using Gemini into a structured JSON format.

        Args:
            original_prompt: The initial, unstructured prompt from the user.
            target_type: The target output type (IMAGE or VIDEO).
            prompt_template: The instruction template for the Gemini model.

        Returns:
            A dictionary parsed from Gemini's JSON response.

        """
        full_prompt = f"{prompt_template} {original_prompt}"
        contents: Any = (
            [*extra_parts, full_prompt] if extra_parts else full_prompt
        )
        mime_val = response_mime_type.value
        if mime_val not in (
            ResponseMimeTypeEnum.JSON.value,
            ResponseMimeTypeEnum.TEXT.value,
        ):
            return ""
        try:
            schema = (
                response_schema or self._get_response_schema(target_type)
                if mime_val == ResponseMimeTypeEnum.JSON.value
                else None
            )
            response = self.client.models.generate_content(
                model=self.rewriter_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type=mime_val,
                    response_schema=schema,
                ),
            )
            return response.text or ""
        except Exception as e:
            logger.error(
                "Failed to generate structured prompt for '%s': %s",
                original_prompt,
                e,
            )
            raise

    def generate_random_or_rewrite_prompt(
        self,
        target_type: PromptTargetEnum,
        original_prompt: str = "",
    ) -> str:
        """Generates a completely new, random, and creative text prompt."""
        try:
            templates = (
                {
                    PromptTargetEnum.IMAGE: REWRITE_IMAGE_TEXT_PROMPT_TEMPLATE,
                    PromptTargetEnum.AUDIO: REWRITE_AUDIO_TEXT_PROMPT_TEMPLATE,
                }
                if original_prompt
                else {
                    PromptTargetEnum.IMAGE: RANDOM_IMAGE_PROMPT_TEMPLATE,
                    PromptTargetEnum.AUDIO: RANDOM_AUDIO_PROMPT_TEMPLATE,
                }
            )
            default_tpl = (
                REWRITE_VIDEO_TEXT_PROMPT_TEMPLATE
                if original_prompt
                else RANDOM_VIDEO_PROMPT_TEMPLATE
            )
            return self.generate_structured_prompt(
                original_prompt=original_prompt,
                target_type=target_type,
                prompt_template=templates.get(target_type, default_tpl),
                response_mime_type=ResponseMimeTypeEnum.TEXT,
            )
        except Exception as e:
            logger.error("Failed to generate random prompt: %s", e)
            raise

    def _convert_dto_to_string(self, dto: BaseModel) -> str:
        """Private helper to convert DTO into a string for prompting.

        This consolidates the repetitive logic from the original file.
        """
        # Use model_dump_json and reload it to ensure all values, especially
        # enums, are converted to primitive string/number/etc. values
        # instead of their Python object representation.
        json_string = dto.model_dump_json(exclude_unset=True)
        fields = json.loads(json_string)

        # Ensure style parameters are included as empty strings if not provided
        for param in ["style", "color_and_tone", "lighting", "composition"]:
            if param not in fields:
                fields[param] = ""

        # The main 'prompt' field is the base, others are attributes
        prompt_base = fields.pop("prompt", "")

        attributes = [prompt_base]
        for key, value in fields.items():
            if value:  # Ensure value is not None or empty
                formatted_key = key.replace("_", " ").title()
                if key == "aspect_ratio":
                    ratio_labels = {
                        "9:16": "9:16 (Portrait / Vertical format)",
                        "16:9": "16:9 (Landscape / Widescreen format)",
                    }
                    formatted_value = ratio_labels.get(value, str(value))
                else:
                    formatted_value = str(value)
                attributes.append(f"- {formatted_key}: {formatted_value}")
        return "\n".join(filter(None, attributes))

    _AUDIO_ITERATION_MODEL_HINTS = {
        GenerationModelEnum.LYRIA_002: (
            "Target model constraint: Lyria 2 (instrumental only — write a "
            "cohesive ~30-second instrumental prose prompt; do NOT include "
            "vocals, a Lyrics: block, or [m:ss - m:ss] section brackets; "
            "translate any vocal melody from the reference audio into an "
            "expressive lead instrument)."
        ),
        GenerationModelEnum.LYRIA_3_CLIP_PREVIEW: (
            "Target model format: Lyria 3 Clip (~30-second clip — anchor "
            "the [m:ss - m:ss] section timeline within 0:00 to 0:30)."
        ),
        GenerationModelEnum.LYRIA_3_PRO_PREVIEW: (
            "Target model format: Lyria 3 Pro (full-length structured "
            "track up to ~3:00 — explicit [m:ss - m:ss] section timestamps "
            "control exact section timing and total song duration; "
            "preserve the reference track's total duration unless the user "
            "asks to extend, shorten, or add sections)."
        ),
    }

    @staticmethod
    def _format_audio_iteration_prompt(
        dto: CreateImagenDto | CreateVeoDto | CreateAudioDto,
        reference_audio_context: dict[str, Any],
    ) -> str:
        """Builds the structured user/context payload for iterative audio progression."""
        sections: list[str] = []
        hint = GeminiService._AUDIO_ITERATION_MODEL_HINTS.get(
            getattr(dto, "model", None)
        )
        if hint:
            sections.append(hint)

        prior_prompt = (
            reference_audio_context.get("prior_prompt") or ""
        ).strip()
        if prior_prompt:
            sections.append(f"Reference track prior prompt: {prior_prompt}")

        raw_steps = reference_audio_context.get("iteration_steps")
        if isinstance(raw_steps, list):
            clean_steps = [
                s.strip() for s in raw_steps if isinstance(s, str) and s.strip()
            ]
            if clean_steps:
                numbered = "\n".join(
                    f"{i}. {step}" for i, step in enumerate(clean_steps, 1)
                )
                sections.append(
                    "Cumulative iteration history (chronological user requests "
                    f"leading to the reference track):\n{numbered}"
                )

        musical_profile = reference_audio_context.get("musical_profile")
        structure = reference_audio_context.get("structure")
        for label, payload in (
            (
                "Reference track acoustic / musical profile (BPM, key, "
                "harmony, instrumentation)",
                musical_profile,
            ),
            ("Reference track structure and metadata", structure),
        ):
            if payload:
                serialized = (
                    json.dumps(payload, ensure_ascii=False)
                    if isinstance(payload, (dict, list))
                    else str(payload)
                )
                sections.append(f"{label}: {serialized}")

        lyrics = (reference_audio_context.get("lyrics") or "").strip()
        raw_text = (reference_audio_context.get("raw_text") or "").strip()
        if lyrics:
            sections.append(f"Reference track lyrics:\n{lyrics}")
        elif raw_text and not structure and not musical_profile:
            sections.append(f"Reference track notes:\n{raw_text}")

        sections.append(
            "User's iterative progression / modification instructions:\n"
            f"{dto.prompt}"
        )
        negative = (getattr(dto, "negative_prompt", None) or "").strip()
        if negative:
            sections.append(f"Elements to avoid: {negative}")
        return "\n\n".join(sections)

    async def enhance_prompt_from_dto(
        self,
        dto: CreateImagenDto | CreateVeoDto | CreateAudioDto,
        target_type: PromptTargetEnum,
        response_mime_type: ResponseMimeTypeEnum = ResponseMimeTypeEnum.JSON,
        extra_parts: list[types.Part] | None = None,
        reference_audio_context: dict[str, Any] | None = None,
    ) -> str:
        """Enhances a partially filled DTO by converting it to a string.

        Then, asks Gemini to generate a complete, structured prompt.
        This single method replaces the four repetitive `rewrite_for_*` methods.

        Args:
            dto: The input DTO, which can be for an image, video, or audio.
            target_type: The target output type (IMAGE, VIDEO, or AUDIO).

        Returns:
            A dictionary or text prompt string from Gemini.

        """
        if target_type == PromptTargetEnum.AUDIO:
            if reference_audio_context is not None:
                prompt_text = self._format_audio_iteration_prompt(
                    dto, reference_audio_context
                )
                prompt_template = ITERATE_AUDIO_TEXT_PROMPT_TEMPLATE
            else:
                prompt_text = dto.prompt
                negative = (getattr(dto, "negative_prompt", None) or "").strip()
                if negative:
                    prompt_text = (
                        f"{prompt_text}\nElements to avoid: {negative}"
                    )
                prompt_template = REWRITE_AUDIO_TEXT_PROMPT_TEMPLATE
            return await asyncio.to_thread(
                self.generate_structured_prompt,
                original_prompt=prompt_text,
                target_type=PromptTargetEnum.AUDIO,
                prompt_template=prompt_template,
                response_mime_type=ResponseMimeTypeEnum.TEXT,
                extra_parts=extra_parts,
            )

        if target_type not in [PromptTargetEnum.IMAGE, PromptTargetEnum.VIDEO]:
            raise ValueError(
                "Invalid target_type. Must be IMAGE, VIDEO, or AUDIO."
            )

        # --- Prompt Enhancement for Gemini Image-to-Image ---
        # This logic is placed here to ensure that any call to enhance a prompt
        # for Gemini Flash i2i will automatically include these critical
        # instructions, making the behavior consistent across the application.
        is_gemini_i2i = (
            isinstance(dto, CreateImagenDto)
            and dto.generation_model.is_gemini_image_model
            and (dto.source_asset_ids or dto.source_media_items)
        )

        if is_gemini_i2i:
            dto.prompt = (
                "**Objective:** Perform a targeted edit on the source image "
                "based on the user's request.\n"
                "**Guiding Principle:** Your primary goal is to follow the "
                "user's instructions precisely. Preserve all aspects of the "
                "original image (subject identity, background, lighting, "
                "composition) unless the user's request explicitly requires "
                "a change.\n\n"
                "**Execution Flow:** Analyze the user's request and match it "
                "to one of the following scenarios. If no scenario fits "
                "perfectly, use the 'General Instruction' as a fallback.\n\n"
                "--- Scenarios ---\n\n"
                "**1. Garment/Accessory Edit** (e.g., 'change the shirt to "
                "blue', 'add sunglasses')\n"
                "   - **Action:** Isolate and modify only the specified "
                "clothing or accessory item.\n"
                "   - **Constraint:** You **MUST NOT** change the subject's "
                "identity, face, pose, or the background.\n\n"
                "**2. Background Replacement** (e.g., 'change the background "
                "to a beach', 'put them in Paris')\n"
                "   - **Action:** Replace the entire background with the new "
                "scene described.\n"
                "   - **Constraint:** You **MUST** preserve the foreground "
                "subject's identity, pose, and clothing. Adjust lighting on "
                "the subject only as needed to blend them realistically into "
                "the new background.\n\n"
                "**3. Pose Adjustment** (e.g., 'make them wave', 'change "
                "the pose to sitting')\n"
                "   - **Action:** Adjust the subject's body to the new "
                "pose.\n"
                "   - **Constraint:** You **MUST** preserve the subject's "
                "identity, clothing, and the background environment.\n\n"
                "**4. Outpainting / Zoom Out** (e.g., 'zoom out', 'show "
                "more of the scene', 'make it a wide-angle shot')\n"
                "   - **Action:** Extend the image outwards by generating "
                "new content that seamlessly matches the existing style "
                "(outpainting).\n"
                "   - **Default:** If the user just says 'zoom out', "
                "interpret it as 'zoom out by at least 2x'. If they specify "
                "a different amount, follow their instruction.\n\n"
                "**5. General Instruction (Fallback):**\n"
                "   - **Action:** If the request does not fit the scenarios "
                "above, follow the user's instructions as literally as "
                "possible.\n"
                "   - **Constraint:** Make the minimum necessary changes to "
                "fulfill the request, preserving as much of the original "
                "image as you can.\n\n"
                "--- End of Scenarios ---\n\n"
                f"**User's Request:** {dto.prompt}"
            )

            # For Gemini image-to-image, we do NOT want to rewrite the prompt
            # into a complex JSON structure. The detailed instructions above
            # are designed to be sent directly to the model to ensure it makes
            # minimal, targeted changes. Bypassing the structured prompt
            # generation prevents the model from deforming or completely
            # changing the original image.
            # We also set the response mime type to TEXT to reflect this.
            return dto.prompt

        # --- Prepend Brand Guidelines if available ---
        if dto.use_brand_guidelines and dto.workspace_id and not is_gemini_i2i:
            search_dto = BrandGuidelineSearchDto(
                workspace_id=dto.workspace_id, limit=1
            )
            guideline_response = await self.brand_guideline_repo.query(
                search_dto,
                workspace_id=dto.workspace_id,
            )

            if guideline_response and guideline_response.data:
                guideline = guideline_response.data[0]
                # Construct a prefix to guide the prompt rewriter.
                prefix_parts = [
                    "Based on the following brand guidelines, "
                    "enhance the user's prompt.",
                ]
                if guideline.visual_style_summary:
                    prefix_parts.append(
                        f"**Visual Style:** {guideline.visual_style_summary}",
                    )
                if guideline.tone_of_voice_summary:
                    prefix_parts.append(
                        f"**Tone of Voice:** {guideline.tone_of_voice_summary}",
                    )
                prefix_parts.append("\n---")
                brand_guideline_prefix = "\n".join(prefix_parts) + "\n\n"
                dto.prompt = brand_guideline_prefix + dto.prompt
            else:
                logger.info(
                    "No brand guidelines found for workspace '%s'.",
                    dto.workspace_id,
                )

        prompt_template = (
            REWRITE_IMAGE_JSON_PROMPT_TEMPLATE
            if target_type == PromptTargetEnum.IMAGE
            else REWRITE_VIDEO_JSON_PROMPT_TEMPLATE
        )
        prompt_string = self._convert_dto_to_string(dto)

        return self.generate_structured_prompt(
            original_prompt=prompt_string,
            target_type=target_type,
            prompt_template=prompt_template,
            response_mime_type=response_mime_type,
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        # Only quota / 503 / network errors (Q10); never safety or 4xx.
        retry=retry_if_exception(is_transient_or_quota),
        reraise=True,
    )
    def generate_text(self, prompt: str, model_id: str | None = None) -> str:
        """Generates plain text from a prompt using Gemini.

        General-purpose method for simple text-in, text-out.

        Args:
            prompt: The text prompt to send to the model.
            model_id: Optional. Gemini model ID to use, overriding default.

        Returns:
            A string containing the generated text from the model.

        Raises:
            Exception: Propagates exceptions from the API call.

        """
        # Use provided model_id or fall back to service's default rewriter model
        target_model = model_id or self.rewriter_model

        logger.info(
            "Sending text generation request to model: %s", target_model
        )
        try:
            response = self.client.models.generate_content(
                model=target_model,
                contents=prompt,
                # Configure for a simple text response without a schema
                config=types.GenerateContentConfig(
                    response_mime_type="text/plain"
                ),
            )
            logger.info("Successfully received text response from Gemini.")
            # Strip any leading/trailing whitespace from the response
            return response.text.strip() if response.text else ""
        except Exception as e:
            logger.error(
                "Gemini text generation failed for prompt '%s...': %s",
                prompt[:100],
                e,
            )
            raise

    def generate_title_and_summary(self, text: str) -> dict[str, Any]:
        """Generates a short title and a summary for a conversation starter.

        Args:
            text: The conversation starter text.

        Returns:
            A dictionary with 'title' and 'summary'.
        """
        prompt = (
            "Generate a short title and a summary for a conversation "
            f"that starts with the following message.\nMessage: {text}"
        )

        # Import inside to avoid circular imports if any
        # pylint: disable=import-outside-toplevel
        from src.multimodal.dto.gemini_prompt_enhancer_dto import (
            GenerateTitleResponseDto,
        )

        try:
            response = self.client.models.generate_content(
                model=self.rewriter_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=GenerateTitleResponseDto,
                ),
            )
            return json.loads(response.text or "{}")
        except Exception as e:
            logger.error("Failed to generate title and summary: %s", e)
            raise

    _MEDIA_EXT_MIMES = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".mp4": "video/mp4",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".mp3": "audio/mpeg",
    }

    @staticmethod
    def _compact_musical_profile(raw_profile: Any) -> dict[str, Any] | None:
        """Validates and compacts a raw musical profile dict into snake_case."""
        if not isinstance(raw_profile, dict) or not raw_profile:
            return None
        try:
            dumped = MusicalProfileDto.model_validate(raw_profile).model_dump(
                exclude_none=True
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Ignoring malformed musical_profile payload: %s", e)
            return None

        cleaned: dict[str, Any] = {}
        for key, val in dumped.items():
            if isinstance(val, str):
                if val.strip():
                    cleaned[key] = val.strip()
            elif isinstance(val, list):
                items = [
                    str(v).strip()
                    for v in val
                    if v is not None and str(v).strip()
                ]
                if items:
                    cleaned[key] = items
            elif val is not None:
                cleaned[key] = val
        return cleaned or None

    def generate_media_metadata(
        self,
        prompt: str,
        media_uris: list[str] | str | None,
        model_name: str,
        mime_type: str | None = None,
        include_audio_profile: bool = False,
    ) -> dict[str, Any]:
        """Generates titles and descriptions (and optional audio profiles) in batch."""
        uris_list = (
            [media_uris]
            if isinstance(media_uris, str)
            else (media_uris if isinstance(media_uris, list) else [])
        )

        contents: list[Any] = []
        for media_uri in uris_list:
            try:
                resolved_mime = mime_type
                if not resolved_mime:
                    uri_lower = media_uri.lower()
                    ext = (
                        f".{uri_lower.rsplit('.', 1)[-1]}"
                        if "." in uri_lower
                        else ""
                    )
                    resolved_mime = self._MEDIA_EXT_MIMES.get(ext) or (
                        "video/mp4"
                        if "video" in uri_lower
                        else (
                            "audio/mpeg"
                            if "audio" in uri_lower
                            else "image/png"
                        )
                    )
                contents.append(
                    types.Part.from_uri(
                        file_uri=media_uri, mime_type=resolved_mime
                    )
                )
            except Exception as e:
                logger.warning(
                    "Failed to create Part from URI %s: %s", media_uri, e
                )

        batch_prompt = (
            f"{prompt}\nGenerate a title and description for EACH of the"
            f" {len(uris_list)} media items provided, in exact sequential"
            " order."
        )
        if include_audio_profile:
            batch_prompt += (
                " Also analyze each audio item's musical characteristics to"
                " populate musicalProfile (bpm, keySignature, timeSignature,"
                " chordProgression, groove, instrumentation, vocalProfile)."
            )
        contents.append(batch_prompt)

        schema_cls = (
            GenerateAudioMediaMetadataResponseDto
            if include_audio_profile
            else GenerateMediaMetadataResponseDto
        )
        try:
            response = self.client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema_cls,
                ),
            )
            raw_items = json.loads(response.text or "{}").get("items") or []
            dict_items = [i for i in raw_items if isinstance(i, dict)]
            result: dict[str, Any] = {
                "titles": [i.get("title", "") for i in dict_items],
                "descriptions": [i.get("description", "") for i in dict_items],
            }
            if include_audio_profile:
                result["musical_profiles"] = [
                    self._compact_musical_profile(
                        i["musicalProfile"]
                        if "musicalProfile" in i
                        else i.get("musical_profile")
                    )
                    for i in dict_items
                ]
            return result
        except Exception as e:
            logger.error("Failed to generate media metadata: %s", e)
            raise

    def extract_brand_info_from_pdf(self, pdf_gcs_uri: str) -> dict[str, Any]:
        """Extracts brand info from a PDF in GCS using Gemini.

        Args:
            pdf_gcs_uri: The full GCS URI (gs://bucket/...) of the PDF.

        Returns:
            A dictionary containing the extracted brand information.

        """
        logger.info("Starting brand info extraction for PDF: %s", pdf_gcs_uri)

        pdf_file = types.Part.from_uri(
            file_uri=pdf_gcs_uri,
            mime_type="application/pdf",
        )

        # This structured prompt instructs the model to return a JSON object,
        # making the output easy to parse and use.
        prompt = """
        Analyze the provided brand guidelines PDF and extract the following information into a structured JSON object:
        1.  "colorPalette": A list of the primary brand colors as hex codes (e.g., ["#RRGGBB", ...]).
        2.  "toneOfVoiceSummary": A detailed and comprehensive summary of the brand's tone of voice, approximately 200-250 words, formatted in Markdown. This summary should be suitable for use as a prefix in a text generation prompt, capturing nuances like personality, vocabulary, and attitude.
        3.  "visualStyleSummary": A detailed and comprehensive summary of the brand's visual style, aesthetics, and imagery, approximately 5000-6000 words, formatted in Markdown. This summary should be suitable for use as a prefix in an image generation prompt, covering aspects like photography style, graphic elements, and overall mood.

        Your response MUST be a single, valid JSON object and nothing else.
        """

        try:
            response = self.client.models.generate_content(
                model=self.cfg.GEMINI_MODEL_ID,
                contents=[pdf_file, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=BrandGuidelineModel,
                ),
            )

            # Model returns JSON, parse it directly.
            extracted_data = json.loads(response.text or "{}")
            return extracted_data
        except Exception as e:
            logger.error(
                "Failed to extract brand info from PDF %s: %s", pdf_gcs_uri, e
            )
            return {}

    def aggregate_brand_info(
        self,
        partial_results: list[dict[str, Any]],
    ) -> BrandGuidelineModel | None:
        """Aggregates multiple partial brand info extractions.

        Uses Gemini to consolidate them.

        Args:
            partial_results: A list of dictionaries of partial extractions.

        Returns:
            A BrandGuidelineModel object with combined info, or None on failure.

        """
        if not partial_results:
            return None
        if len(partial_results) == 1:
            return BrandGuidelineModel(**partial_results[0])

        logger.info(
            "Aggregating %s partial brand info results.", len(partial_results)
        )

        # --- Step 1: Deterministic Aggregation in Python ---
        # Combine color palettes and get unique hex codes, case-insensitively.
        all_colors = set()
        for result in partial_results:
            if result.get("colorPalette"):
                # Filter out potential non-string or empty values
                valid_colors = [
                    c
                    for c in result["colorPalette"]
                    if isinstance(c, str) and c
                ]
                all_colors.update(c.upper() for c in valid_colors)

        # Collect all non-empty text summaries.
        tone_summaries = [
            r.get("toneOfVoiceSummary")
            for r in partial_results
            if r.get("toneOfVoiceSummary")
        ]
        visual_summaries = [
            r.get("visualStyleSummary")
            for r in partial_results
            if r.get("visualStyleSummary")
        ]

        # --- Step 2: AI-powered Aggregation for Summaries ---
        # Ask Gemini to synthesize the text fields into final summaries.
        prompt = f"""
        You are an expert in brand identity. You have been given partial data extracted from a large brand guidelines document. Your task is to synthesize this data into a single, final, and coherent JSON object.

        1.  **Color Palette**: Here is a list of all hex color codes found across the document chunks. Your task is to select the most representative and primary brand colors to create the final palette. **Crucially, you MUST NOT invent new colors.** Choose only from this list:
            {json.dumps(sorted(list(all_colors)), indent=2)}

        2.  **Tone of Voice Summaries**: Here are the partial summaries describing the brand's voice:
            {json.dumps(tone_summaries, indent=2)}

        3.  **Visual Style Summaries**: Here are the partial summaries describing the brand's visual style:
            {json.dumps(visual_summaries, indent=2)}

        Please generate a final, consolidated JSON object with three keys:
        -   "color_palette": A list of hex strings representing the final, curated brand colors, chosen from the list provided.
        -   "tone_of_voice_summary": A single, comprehensive, and well-written summary of approximately 200-250 words that synthesizes all aspects of the brand's voice from the partial summaries, formatted in Markdown.
        -   "visual_style_summary": A single, comprehensive, and well-written summary of approximately 5000-6000 words that synthesizes all aspects of the brand's visual identity from the partial summaries, formatted in Markdown.

        Your response MUST be a single, valid JSON object and nothing else.
        """

        try:
            # Model subset used, schema can be BrandGuidelineModel.
            response = self.client.models.generate_content(
                model=self.rewriter_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=BrandGuidelineModel,
                ),
            )

            # --- Step 3: Combine Python and AI results ---
            aggregated_data = json.loads(response.text or "{}")
            return BrandGuidelineModel(**aggregated_data)
        except Exception as e:
            logger.error(
                "Failed to aggregate brand info summaries with Gemini: %s", e
            )
            return None

    async def generate_multimodal(
        self,
        request: MultimodalGenerationRequestDto,
    ) -> str:
        """Generates text from a multimodal prompt combining text and media."""
        contents = []

        # Add MediaItems
        media_item_ids = request.media_items or request.media_item_ids
        if media_item_ids:
            for item_id in media_item_ids:
                media_item = await self.media_item_repo.get_by_id(item_id)
                if media_item:
                    if media_item.workspace_id != request.workspace_id:
                        raise HTTPException(
                            status_code=403,
                            detail=f"Media item {item_id} does not belong to workspace {request.workspace_id}",
                        )
                    if (
                        getattr(media_item, "gcs_uris", None)
                        and len(media_item.gcs_uris) > 0
                    ):
                        contents.append(
                            types.Part.from_uri(
                                file_uri=media_item.gcs_uris[0],
                                mime_type=media_item.mime_type or "image/png",
                            )
                        )

        # Add SourceAssets
        source_asset_ids = request.assets or request.source_asset_ids
        if source_asset_ids:
            for asset_id in source_asset_ids:
                asset = await self.source_asset_repo.get_by_id(asset_id)
                if asset:
                    if asset.workspace_id != request.workspace_id:
                        raise HTTPException(
                            status_code=403,
                            detail=f"Asset {asset_id} does not belong to workspace {request.workspace_id}",
                        )
                    if asset.gcs_uri:
                        contents.append(
                            types.Part.from_uri(
                                file_uri=asset.gcs_uri,
                                mime_type=asset.mime_type or "image/png",
                            )
                        )

        # Append the text prompt
        contents.append(request.prompt)

        config_args = {}
        if request.config:
            config_args = {
                "config": types.GenerateContentConfig(**request.config)
            }

        try:
            response = await self.client.aio.models.generate_content(
                model=request.model,
                contents=contents,
                **config_args,
            )
            return response.text or ""
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            logger.error("Failed to generate multimodal content: %s", e)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate multimodal content: {e}",
            )
