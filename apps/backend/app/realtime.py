import asyncio
import json
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .db import SessionLocal, get_db
from .models import RealtimeEvent, User, UserRole
from .security import JWT_ALGORITHM, JWT_SECRET, validate_token_user

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked session") from exc


def emit_realtime_event(
    db: Session,
    topic: str,
    *,
    tenant_id: int | None = None,
    user_id: int | None = None,
    audience: str = "user",
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    payload: dict | None = None,
) -> RealtimeEvent:
    if audience not in {"user", "tenant_staff", "tenant_all", "platform_admins"}:
        raise ValueError("Unsupported realtime audience")
    if audience == "user" and not user_id:
        raise ValueError("User-targeted realtime events require user_id")
    if audience in {"tenant_staff", "tenant_all"} and not tenant_id:
        raise ValueError("Tenant realtime events require tenant_id")
    event = RealtimeEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        topic=topic,
        audience=audience,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        payload_json=json.dumps(payload or {}, separators=(",", ":"), default=str),
    )
    db.add(event)
    db.flush()
    return event


def _event_visible(user: User, event: RealtimeEvent) -> bool:
    if user.role == UserRole.SUPER_ADMIN:
        return True
    if event.audience == "user":
        return event.user_id == user.id
    if event.audience == "tenant_all":
        return bool(user.tenant_id and event.tenant_id == user.tenant_id)
    if event.audience == "tenant_staff":
        return bool(
            user.tenant_id
            and event.tenant_id == user.tenant_id
            and (user.is_tenant_admin or user.role in {UserRole.REVIEWER, UserRole.PUBLISHER})
        )
    return False


def _fetch_visible_events(user_id: int, after_id: int, limit: int = 100) -> list[dict]:
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user or not user.is_active:
            return []
        query = select(RealtimeEvent).where(RealtimeEvent.id > after_id).order_by(RealtimeEvent.id).limit(limit)
        rows = list(db.scalars(query))
        result = []
        for row in rows:
            if not _event_visible(user, row):
                continue
            try:
                payload = json.loads(row.payload_json or "{}")
            except Exception:
                payload = {}
            result.append({
                "id": row.id,
                "topic": row.topic,
                "audience": row.audience,
                "tenant_id": row.tenant_id,
                "user_id": row.user_id,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "payload": payload,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })
        return result
    finally:
        db.close()


def _ticket_for(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user.id),
            "purpose": "realtime",
            "iat": now,
            "exp": now + timedelta(seconds=90),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def _user_id_from_ticket(ticket: str) -> int:
    payload = jwt.decode(ticket, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    if payload.get("purpose") != "realtime":
        raise ValueError("Invalid realtime ticket")
    return int(payload["sub"])


@router.post("/api/v1/realtime/ticket")
def realtime_ticket(user: User = Depends(current_user)):
    return {"ticket": _ticket_for(user), "expires_in": 90}


@router.websocket("/api/v1/realtime/ws")
async def realtime_ws(websocket: WebSocket):
    ticket = websocket.query_params.get("ticket")
    if not ticket:
        await websocket.close(code=4401)
        return
    try:
        user_id = _user_id_from_ticket(ticket)
    except Exception:
        await websocket.close(code=4401)
        return

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or not user.is_active:
            await websocket.close(code=4403)
            return

    await websocket.accept()
    try:
        raw_after = websocket.query_params.get("after")
        last_id = int(raw_after) if raw_after and raw_after.isdigit() else 0
        await websocket.send_json({"type": "ready", "last_event_id": last_id})
        while True:
            events = await asyncio.to_thread(_fetch_visible_events, user_id, last_id)
            for event in events:
                last_id = max(last_id, int(event["id"]))
                await websocket.send_json({"type": "event", **event})
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                if message == "ping":
                    await websocket.send_json({"type": "pong", "last_event_id": last_id})
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        return


def cleanup_realtime_events(db: Session, retention_hours: int = 48) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, retention_hours))
    rows = list(db.scalars(select(RealtimeEvent).where(RealtimeEvent.created_at < cutoff).limit(5000)))
    count = len(rows)
    for row in rows:
        db.delete(row)
    if count:
        db.commit()
    return count
