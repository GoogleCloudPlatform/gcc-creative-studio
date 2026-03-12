import asyncio
import logging
from typing import Dict, List, AsyncGenerator
from google.adk.events import Event

logger = logging.getLogger(__name__)

class EventBus:
    """
    Simple in-memory Event Bus to broadcast ADK events to subscribers (SSE clients).
    Keyed by session_id.
    """
    def __init__(self):
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}

    def subscribe(self, session_id: str) -> asyncio.Queue:
        """
        Subscribe to events for a specific session.
        Returns an asyncio.Queue that will receive Event objects (or formatted strings).
        """
        if session_id not in self._subscribers:
            self._subscribers[session_id] = []
        
        queue = asyncio.Queue()
        self._subscribers[session_id].append(queue)
        logger.info(f"New subscriber for session {session_id}. Total: {len(self._subscribers[session_id])}")
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue):
        """
        Unsubscribe a queue from a session.
        """
        if session_id in self._subscribers:
            if queue in self._subscribers[session_id]:
                self._subscribers[session_id].remove(queue)
            
            if not self._subscribers[session_id]:
                del self._subscribers[session_id]

    async def publish(self, session_id: str, event: Event):
        """
        Publish an ADK event to all subscribers of the session.
        """
        if session_id in self._subscribers:
            for queue in self._subscribers[session_id]:
                await queue.put(event)

    async def stream_events(self, session_id: str) -> AsyncGenerator[str, None]:
        """
        Yields SSE-formatted events for a session.
        """
        queue = self.subscribe(session_id)
        
        # 1. Send initial byte to avoid 'first byte timeout' from proxies/GFE
        # This starts the response headers and initial body chunk.
        yield ": ok\n\n"

        try:
            while True:
                try:
                    # 2. Wait for event with a timeout for heartbeat
                    # If no event happens within 15s, we send a keep-alive comment.
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    
                    # Format as SSE
                    # ADK Events are Pydantic models (usually)
                    data = event.model_dump_json() if hasattr(event, "model_dump_json") else str(event)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    # 3. Send heartbeat to keep connection alive
                    yield ": keep-alive\n\n"
        except asyncio.CancelledError:
            logger.info(f"Stream cancelled for session {session_id}")
        finally:
            self.unsubscribe(session_id, queue)

# Global Instance (or use Dependency Injection)
_event_bus = EventBus()

def get_event_bus() -> EventBus:
    return _event_bus
