from contextvars import ContextVar

# Context variable to track if the current request originated from an agent
is_agent_request: ContextVar[bool] = ContextVar("is_agent_request", default=False)
