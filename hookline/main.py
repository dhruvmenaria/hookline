import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .config import settings
from .db import Base, engine, get_session
from .models import DeliveryAttempt, Event
from .schemas import EventEnvelope, ReplayRequest
from .signing import verify_signature
from .worker import deliver

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="Hookline", version="0.1.0", description="Webhook reliability inbox and retry console", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def event_view(event: Event, include_attempts: bool = False) -> dict:
    result = {
        "id": event.id,
        "event_id": event.event_id,
        "idempotency_key": event.idempotency_key,
        "event_type": event.event_type,
        "source": event.source,
        "payload": json.loads(event.payload),
        "status": event.status,
        "attempts": event.attempts,
        "last_error": event.last_error,
        "next_attempt_at": event.next_attempt_at,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }
    if include_attempts:
        result["delivery_attempts"] = [{
            "attempt_number": a.attempt_number, "outcome": a.outcome,
            "message": a.message, "created_at": a.created_at,
        } for a in event.delivery_attempts]
    return result


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "hookline"}


@app.post("/api/events", status_code=202)
async def receive_event(
    request: Request,
    signature: str = Header(default="", alias="X-Hookline-Signature"),
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_session),
):
    raw = await request.body()
    if not signature or not verify_signature(raw, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(status_code=400, detail="A valid Idempotency-Key header is required")
    try:
        body = EventEnvelope.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Request body is not a valid event envelope") from exc
    digest = hashlib.sha256(raw).hexdigest()
    existing = await db.scalar(select(Event).where(Event.idempotency_key == idempotency_key))
    if existing:
        if existing.body_hash != digest:
            raise HTTPException(status_code=409, detail="Idempotency key was already used with a different body")
        return {**event_view(existing), "duplicate": True}

    event = Event(event_id=body.event_id, idempotency_key=idempotency_key, body_hash=digest,
                  event_type=body.event_type, source=body.source, payload=json.dumps(body.payload), status="queued")
    db.add(event)
    try:
        await db.flush()
        attempt = await deliver(event)
        db.add(attempt)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        winner = await db.scalar(select(Event).where(Event.idempotency_key == idempotency_key))
        if winner and winner.body_hash == digest:
            return {**event_view(winner), "duplicate": True}
        raise HTTPException(status_code=409, detail="Idempotency key conflict")
    await db.refresh(event)
    return {**event_view(event), "duplicate": False}


@app.get("/api/events")
async def list_events(status: str | None = None, limit: int = 100, db: AsyncSession = Depends(get_session)):
    limit = max(1, min(limit, 200))
    query = select(Event).order_by(Event.created_at.desc()).limit(limit)
    if status and status != "all":
        query = query.where(Event.status == status)
    events = (await db.scalars(query)).all()
    return [event_view(event) for event in events]


@app.get("/api/events/{event_pk}")
async def get_event(event_pk: int, db: AsyncSession = Depends(get_session)):
    event = await db.scalar(select(Event).options(selectinload(Event.delivery_attempts)).where(Event.id == event_pk))
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event_view(event, include_attempts=True)


@app.post("/api/events/{event_pk}/retry")
async def retry_event(event_pk: int, request: ReplayRequest, db: AsyncSession = Depends(get_session)):
    event = await db.get(Event, event_pk)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.status not in {"retry_wait", "dead_letter"}:
        raise HTTPException(status_code=409, detail=f"Event in {event.status} state cannot be retried")
    if event.attempts >= settings.max_attempts and not request.force:
        raise HTTPException(status_code=409, detail="Attempt limit reached; set force=true to replay manually")
    event.status = "queued"
    event.next_attempt_at = None
    await db.flush()
    attempt = await deliver(event)
    db.add(attempt)
    await db.commit()
    event = await db.scalar(select(Event).options(selectinload(Event.delivery_attempts)).where(Event.id == event_pk))
    return event_view(event, include_attempts=True)


@app.get("/api/metrics")
async def metrics(db: AsyncSession = Depends(get_session)):
    async def count(*conditions):
        return int((await db.scalar(select(func.count()).select_from(Event).where(*conditions))) or 0)
    total = int((await db.scalar(select(func.count()).select_from(Event))) or 0)
    return {
        "total": total,
        "queued": await count(Event.status == "queued"),
        "delivered": await count(Event.status == "delivered"),
        "retry_wait": await count(Event.status == "retry_wait"),
        "dead_letter": await count(Event.status == "dead_letter"),
    }
