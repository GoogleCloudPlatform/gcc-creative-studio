import logging
import asyncio
from enum import Enum
from typing import Dict, Any, List, AsyncGenerator
from fastapi import Depends, BackgroundTasks

# ADK Imports
from google.adk.runners import Runner
from google.adk.agents import SequentialAgent
from google.adk.events.event import Event
from google.genai import types

# Backend Imports
from src.agents.dto.agent_dto import AgentGenerationRequest, AgentGenerationResponse, MediaTypeEnum
from src.images.dto.create_imagen_dto import CreateImagenDto, AspectRatioEnum
from src.videos.dto.create_veo_dto import CreateVeoDto
from src.audios.dto.create_audio_dto import CreateAudioDto
from src.common.base_dto import GenerationModelEnum
from src.videos.veo_service import VeoService
from src.audios.audio_service import AudioService
from src.images.imagen_service import ImagenService
from src.users.user_model import UserModel
from src.audios.audio_constants import VoiceEnum, LanguageEnum
from src.common.schema.media_item_model import JobStatusEnum
from src.database import get_conn_string, get_connection # Import helpers
from src.config.config_service import config_service

# New ADK Agents
from src.agents.adk.enforcer import BrandingEnforcerADK
from src.agents.adk.validator import ValidatorADK
from src.tools.adk_wrappers import create_adk_search_tool
from src.common.vector_search_service import VectorSearchService
from src.multimodal.gemini_service import GeminiService
from src.brand_guidelines.repository.brand_guideline_repository import BrandGuidelineRepository
from src.common.event_bus import get_event_bus, EventBus
from src.common.concurrency import get_global_executor
from google.adk.sessions import DatabaseSessionService # Use persistent service

logger = logging.getLogger(__name__)

class AgentService:
    """
    Orchestrates the Agentic RAG flow using Google ADK.
    Phase 1: Enforcer -> Generator (Sync/Fast).
    Validation is triggered via background polling (as before) but can use ADK Validator.
    """

    def __init__(
        self,
        # Services required for Factory
        vector_search_service: VectorSearchService = Depends(),
        gemini_service: GeminiService = Depends(),
        executor: Any = Depends(get_global_executor),
    ):
        # We now use a factory to create everything needed for the background tasks.
        # This keeps the 'service locator' pattern out of the business logic.
        from src.agents.scoped_agent_factory import ScopedAgentFactory
        
        self.factory = ScopedAgentFactory(
            vector_search_service=vector_search_service,
            gemini_service=gemini_service,
            executor=executor
        )
        
        # Use persistent DatabaseSessionService instead of InMemorySessionService
        # This allows polling from any instance in a horizontally scaled environment
        db_url = get_conn_string()
        engine_kwargs = {}
        
        # Use Cloud SQL Connector if configured
        if config_service.INSTANCE_CONNECTION_NAME and not config_service.USE_CLOUD_SQL_AUTH_PROXY:
            engine_kwargs["async_creator"] = get_connection
            
        self.session_service = DatabaseSessionService(db_url=db_url, **engine_kwargs)
        self.event_bus = get_event_bus()


    async def generate_compliant_media(
        self, 
        request: AgentGenerationRequest, 
        current_user: UserModel,
        background_tasks: BackgroundTasks
    ) -> AgentGenerationResponse:
        """
        Executes the ADK workflow.
        """
        logger.info(f"Starting ADK agentic generation for user {current_user.email} - Type: {request.media_type}")
        
        # 1. Setup Session State
        import time
        session_id = f"sess_{request.workspace_id}_{current_user.email}_{int(time.time() * 1000)}"
        state = {
            "original_prompt": request.prompt,
            "workspace_id": str(request.workspace_id),
            "media_type": request.media_type.value if hasattr(request.media_type, 'value') else request.media_type,
            "current_user": current_user, # Still passing for ID access, but we'll fetch fresh user in BG if needed
            "request_config": {
                "generation_model": request.generation_model,
                "aspect_ratio": request.aspect_ratio,
                "number_of_media": request.number_of_media,
                "style": request.style,
                "duration_seconds": request.duration_seconds,
                "generate_audio": request.generate_audio,
                "voice_name": request.voice_name
            },
            "user_reference_image_uri": request.reference_image_uri,
            "reference_image_uris": [], # Will be populated by Enforcer if applicable
            "current_user": current_user.model_dump(mode='json') if hasattr(current_user, "model_dump") else current_user
        }
        
        # We start the background task
        background_tasks.add_task(
            self._run_director_background,
            request=request,
            user_id=current_user.email,
            session_id=session_id,
            state=state
        )
        
        logger.info(f"Agentic flow started in background. Session: {session_id}")
        
        # Return immediate response (Pending)
        return AgentGenerationResponse(
            original_prompt=request.prompt,
            enhanced_prompt="Processing...",
            generated_assets=[],
            session_id=session_id
        )

    async def _run_director_background(self, request: AgentGenerationRequest, user_id: str, session_id: str, state: Dict[str, Any]):
        """
        Background task to run the Deterministic Media Pipeline.
        """
        from src.database import AsyncSessionLocal
        
        # Create a fresh DB session for the background task
        async with AsyncSessionLocal() as session:
            try:
                logger.info(f"[_run_director_background] Starting for {session_id}")
                
                # Use Factory to get properly Scoped Agents
                components = self.factory.create_components(session)
                pipeline = components["pipeline"]
                
                await self.session_service.create_session(
                    app_name="adk",
                    user_id=user_id,
                    session_id=session_id,
                    state=state
                )
                
                pipeline_runner = Runner(
                    agent=pipeline,
                    app_name="adk",
                    session_service=self.session_service
                )
                
                start_instruction = (
                    f"Please enforce guidelines for the following request:\n"
                    f"Workspace ID: {state.get('workspace_id')}\n"
                    f"Prompt: {state.get('original_prompt')}\n"
                    f"Media Type: {state.get('media_type')}"
                )
                
                trigger_msg = types.Content(role="user", parts=[types.Part(text=start_instruction)])
                
                # Run the pipeline. The Runner automatically saves events to session_service.
                # The frontend polls the history endpoint to see these events.
                async for event in pipeline_runner.run_async(user_id=user_id, session_id=session_id, new_message=trigger_msg):
                    logger.info(f"[Pipeline Event] {event.author}: {event}")
                    # We no longer need to manually publish to event_bus here as 
                    # DatabaseSessionService handles persistence for polling.

            except Exception as e:
                logger.error(f"Background ADK Pipeline Failed: {e}", exc_info=True)
                # Publish error event to user
                await self.event_bus.publish(f"user_{user_id}", Event(author="System", content=types.Content(parts=[types.Part(text=f"Agent process failed: {str(e)}")]) ))


    async def _run_async_validation(self, job_id: int, guidelines: str, prompt: str, user_id: str):
        """
        Runs the ValidatorADK in a separate ephemeral session/runner.
        Detailed: Creates a fresh DB session to avoid 'Session is closed' errors in background tasks.
        """
        # NOTE: This method might be deprecated if the main pipeline includes Validator.
        # But if we still need ad-hoc validation triggered externally, we use the factory.
        
        logger.info(f"Triggering Async Validation for Job {job_id}")
        
        from src.database import AsyncSessionLocal
        
        # Create a fresh session for the background task
        async with AsyncSessionLocal() as session:
            components = self.factory.create_components(session)
            validator = components["validator"]
            media_repo = components["media_repo"]
            
            session_id = f"val_sess_{job_id}"
            state = {
                "job_id": job_id,
                "guidelines_used": guidelines,
                "original_prompt": prompt
            }
            
            await self.session_service.create_session(app_name="GCCCreativeStudio", user_id=user_id, session_id=session_id, state=state)
            
            runner = Runner(
                agent=validator,
                app_name="GCCCreativeStudio",
                session_service=self.session_service
            )
            
            trigger_msg = types.Content(role="user", parts=[types.Part(text=f"Check validation for job {job_id}")])
            async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=trigger_msg):
                 text = event.content.parts[0].text if event.content and event.content.parts else ''
                 logger.info(f"[Validation Event] {event.author}: {text}")
                 await self.event_bus.publish(f"user_{user_id}", event)
            
            # Persist results (Already done by ValidatorADK inside its loop, but we can double check)
            # The ValidatorADK now saves to DB directly.

