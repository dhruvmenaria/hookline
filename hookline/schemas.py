from typing import Any

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    event_id: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=160)
    payload: dict[str, Any]


class ReplayRequest(BaseModel):
    force: bool = False
