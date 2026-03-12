from typing import Optional
from fastapi import APIRouter, Depends, status, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from google.adk.sessions.base_session_service import GetSessionConfig
from src.agents.dto.agent_dto import AgentGenerationRequest, AgentGenerationResponse
from src.agents.agent_service import AgentService
from src.auth.auth_guard import get_current_user
from src.users.user_model import UserModel
from src.common.event_bus import get_event_bus

router = APIRouter(prefix="/api/agents", tags=["Agents"])

@router.post("/generate", response_model=AgentGenerationResponse, status_code=status.HTTP_200_OK)
async def generate_compliant_media(
    request: AgentGenerationRequest,
    background_tasks: BackgroundTasks,
    agent_service: AgentService = Depends(),
    current_user: UserModel = Depends(get_current_user)
):
    """
    Triggers the Agentic RAG workflow: Enforce -> Generate -> Validate (Async).
    """
    return await agent_service.generate_compliant_media(request, current_user, background_tasks)

@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    after_timestamp: Optional[float] = None,
    agent_service: AgentService = Depends(),
    current_user: UserModel = Depends(get_current_user)
):
    """
    Retrieves the history of events for a specific session.
    """
    try:
        session = await agent_service.session_service.get_session(
            app_name="adk",
            user_id=current_user.email,
            session_id=session_id,
            config=GetSessionConfig(after_timestamp=after_timestamp) if after_timestamp else None
        )
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Convert ADK Event objects to dict for serialization
        return [event.model_dump(mode='json', by_alias=True) for event in session.events]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/events/stream", response_class=StreamingResponse)
async def stream_agent_events(current_user: UserModel = Depends(get_current_user)):
    """
    Streams ADK events for the current user. (Legacy/Deprecated in favor of polling)
    """
    event_bus = get_event_bus()
    return StreamingResponse(
        event_bus.stream_events(f"user_{current_user.email}"),
        media_type="text/event-stream"
    )

