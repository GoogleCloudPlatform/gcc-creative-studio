import logging
from typing import AsyncGenerator, Dict, Any

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from src.images.dto.create_imagen_dto import CreateImagenDto
from src.videos.dto.create_veo_dto import CreateVeoDto
from src.audios.dto.create_audio_dto import CreateAudioDto
from src.common.base_dto import GenerationModelEnum, AspectRatioEnum
from src.images.imagen_service import ImagenService
from src.videos.veo_service import VeoService
from src.audios.audio_service import AudioService
from src.users.user_model import UserModel

logger = logging.getLogger(__name__)

from pydantic import PrivateAttr

class MediaGeneratorADK(BaseAgent):
    """
    Custom Agent that wraps backend generation services (Imagen, Veo, Audio).
    It is deterministic and orchestrates the service calls based on session state.
    """
    _imagen_service: Any = PrivateAttr()
    _veo_service: Any = PrivateAttr()
    _audio_service: Any = PrivateAttr()
    _executor: Any = PrivateAttr()

    def __init__(
        self,
        name: str,
        imagen_service: ImagenService,
        veo_service: VeoService,
        audio_service: AudioService,
        executor: Any,
    ):
        super().__init__(name=name)
        self._imagen_service = imagen_service
        self._veo_service = veo_service
        self._audio_service = audio_service
        self._executor = executor
    
    @property
    def imagen_service(self):
        return self._imagen_service

    @property
    def veo_service(self):
        return self._veo_service

    @property
    def audio_service(self):
        return self._audio_service

    @property
    def executor(self):
        return self._executor

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        """
        Reads configuration from state, executes generation, and updates state.
        """
        state = ctx.session.state
        
        
        # 1. Retrieve Context (Hybrid: Message > State)
        # Parse enforcer output if available
        if "enforcer_response_json" in state:
            try:
                import json
                enforcer_data = state["enforcer_response_json"]
                # It might be a string (most likely) or dict if some middleware parsed it
                if isinstance(enforcer_data, str):
                    clean_text = enforcer_data.strip()
                    if clean_text.startswith("```json"):
                         clean_text = clean_text[7:]
                    elif clean_text.startswith("```"):
                         clean_text = clean_text[3:]
                    if clean_text.endswith("```"):
                         clean_text = clean_text[:-3]
                    enforcer_data = json.loads(clean_text)
                
                if isinstance(enforcer_data, dict):
                    if "enhanced_prompt" in enforcer_data:
                        state["enhanced_prompt"] = enforcer_data["enhanced_prompt"]
                        logger.info(f"[{self.name}] Parsed enhanced_prompt from enforcer_response_json.")
                    if "reference_image_uris" in enforcer_data:
                        state["reference_image_uris"] = enforcer_data["reference_image_uris"]
                        logger.info(f"[{self.name}] Parsed reference_image_uris from enforcer_response_json.")
                    if "guidelines_used" in enforcer_data:
                        state["guidelines_used"] = enforcer_data["guidelines_used"]
                        logger.info(f"[{self.name}] Parsed guidelines_used from enforcer_response_json.")
            except Exception as e:
                logger.warning(f"[{self.name}] Failed to parse enforcer_response_json: {e}")

        prompt = state.get("enhanced_prompt") or state.get("original_prompt")
        media_type = state.get("media_type", "IMAGE")
        workspace_id = state.get("workspace_id")
        user_data = state.get("current_user")
        user = user_data
        if isinstance(user_data, dict):
            user = UserModel(**user_data)

        
        # Check if we received instructions directly (Agent-as-a-Tool pattern)
        # The CreativeDirector might say: "Generate image with prompt: '...'"
        # A simple keyword extraction or relying on the session state update which mimics 'arguments' is tricky
        # because AgentTool currently relies on the *conversation* to pass info, NOT structured function call args yet for Agents.
        # BUT, the Director agent's LLM will likely *call* the tool with arguments if it was a FunctionTool.
        # As an AgentTool, the Director sends a *Message*.
        
        import re
        incoming_text = ""
        if ctx.user_content and ctx.user_content.parts:
            incoming_text = ctx.user_content.parts[0].text
            logger.info(f"[{self.name}] Received instructions: {incoming_text}")
            
            # Try parsing as JSON first (Director might pass Enforcer output directly)
            try:
                import json
                # Handle markdown code blocks if present
                clean_text = incoming_text.strip()
                if clean_text.startswith("```json"):
                     clean_text = clean_text[7:]
                elif clean_text.startswith("```"):
                     clean_text = clean_text[3:]
                if clean_text.endswith("```"):
                     clean_text = clean_text[:-3]
                
                data = json.loads(clean_text)
                if isinstance(data, dict):
                    if "enhanced_prompt" in data:
                        prompt = data["enhanced_prompt"]
                        logger.info(f"[{self.name}] Extracted enhanced_prompt from JSON.")
                    if "reference_image_uris" in data and isinstance(data["reference_image_uris"], list):
                        # Update state with these URIs so service can find them
                        state["reference_image_uris"] = data["reference_image_uris"]
                        logger.info(f"[{self.name}] Extracted reference_image_uris from JSON.")
            except json.JSONDecodeError:
                # Not JSON, fall back to regex or raw text
                pass

        # Simple heuristic extraction if prompt is missing or to override
        # If the Director provided a prompt explicitly in quotes (and it wasn't JSON):
        if not prompt:  
            match = re.search(r"prompt:\s*['\"](.*?)['\"]", incoming_text, re.IGNORECASE | re.DOTALL)
            if match:
                 prompt = match.group(1)
                 logger.info(f"[{self.name}] Extracted prompt from message (regex): {prompt}")

        if not prompt:
            yield Event(author=self.name, content=types.Content(parts=[types.Part(text="Error: No prompt found in state or message.")]))
            return

        request_config = state.get("request_config", {}) # Dict of other params
        generation_model = request_config.get("generation_model")
        
        logger.info(f"[{self.name}] Starting generation. Type: {media_type}, Model: {generation_model}, Prompt: {prompt}")
        
        # 2. Dispatch
        media_response = None
        
        try:
            executor = self.executor

            if media_type == "IMAGE":
                # Prepare DTO
                # Combine User Reference (Ingredients) + Brand References (Enforcer)
                # prioritize user provided reference image
                user_ref = state.get("user_reference_image_uri")
                brand_refs = state.get("reference_image_uris") or []
                all_refs = ([user_ref] if user_ref else []) + (brand_refs if isinstance(brand_refs, list) else [])
                
                dto = CreateImagenDto(
                    prompt=prompt,
                    workspace_id=workspace_id,
                    generation_model=generation_model or GenerationModelEnum.GEMINI_2_5_FLASH_IMAGE_PREVIEW,
                    aspect_ratio=request_config.get("aspect_ratio") or AspectRatioEnum.RATIO_1_1,
                    number_of_media=request_config.get("number_of_media", 1),
                    style=request_config.get("style"),
                    reference_image_gcs_uris=all_refs
                )
                media_response = await self.imagen_service.start_image_generation_job(
                    request_dto=dto, 
                    user=user, 
                    executor=executor
                )
                
            elif media_type == "VIDEO":
                dto = CreateVeoDto(
                    prompt=prompt,
                    workspace_id=workspace_id,
                    generation_model=generation_model or GenerationModelEnum.VEO_2_0_001,
                    aspect_ratio=request_config.get("aspect_ratio") or AspectRatioEnum.RATIO_16_9,
                    duration_seconds=request_config.get("duration_seconds", 5),
                    generate_audio=request_config.get("generate_audio", False),
                    style=request_config.get("style")
                )
                media_response = await self.veo_service.start_video_generation_job(
                    request_dto=dto, 
                    user=user, 
                    executor=executor
                )
                
            elif media_type == "AUDIO":
                from src.audios.audio_constants import VoiceEnum, LanguageEnum
                dto = CreateAudioDto(
                    prompt=prompt,
                    workspace_id=workspace_id,
                    model=generation_model or GenerationModelEnum.GEMINI_2_5_FLASH_TTS,
                    voice_name=request_config.get("voice_name") or VoiceEnum.PUCK,
                    language_code=LanguageEnum.EN_US,
                    sample_count=request_config.get("number_of_media", 1)
                )
                media_response = await self.audio_service.generate_audio(
                    request_dto=dto, 
                    user=user
                )
                
            else:
                yield Event(author=self.name, content=types.Content(parts=[types.Part(text=f"Unsupported media type: {media_type}")]))
                return

            # 3. Update State & DB for Provenance
            if media_response:
                # Update DB with prompted lineage if applicable
                original = state.get("original_prompt")
                if original and original != prompt:
                    try:
                        repo = None
                        if media_type == "IMAGE":
                            repo = self.imagen_service.media_repo
                        elif media_type == "VIDEO":
                            repo = self.veo_service.media_repo
                        elif media_type == "AUDIO":
                            repo = self.audio_service.media_repo

                        if repo:
                            await repo.update(media_response.id, {
                                "original_prompt": original,
                                "rewritten_prompt": prompt,
                                "adk_session_id": ctx.session.id
                            })
                            logger.info(f"[{self.name}] Updated MediaItem {media_response.id} with prompt lineage and session ID.")
                    except Exception as e:
                        logger.error(f"[{self.name}] Failed to update prompt lineage: {e}")


                state["generated_assets"] = [{
                    "id": media_response.id,
                    "status": media_response.status,
                    "gcs_uris": media_response.gcs_uris if hasattr(media_response, 'gcs_uris') else []
                }]
                state["job_id"] = media_response.id
                
                yield Event(
                    author=self.name, 
                    content=types.Content(parts=[types.Part(text=f"Generation started. Job ID: {media_response.id}")])
                )
            else:
                yield Event(author=self.name, content=types.Content(parts=[types.Part(text="Generation failed to return a response.")]))

        except Exception as e:
            logger.error(f"Generation failed: {e}")
            yield Event(author=self.name, content=types.Content(parts=[types.Part(text=f"Generation Error: {str(e)}")]))
