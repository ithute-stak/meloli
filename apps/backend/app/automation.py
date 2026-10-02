import json
from datetime import datetime, timedelta, timezone
from typing import Callable, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, AutomationJobState, SystemSetting, User, UserRole
from .realtime import emit_realtime_event
from .security import validate_token_user

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked session") from exc


def platform_admin(user: User = Depends(current_user)) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Platform super admin access required")
    return user


def job_state(db: Session, job_key: str, interval_seconds: int) -> AutomationJobState:
    row = db.scalar(select(AutomationJobState).where(AutomationJobState.job_key == job_key))
    if row is None:
        row = AutomationJobState(job_key=job_key, interval_seconds=max(1, interval_seconds))
        db.add(row)
        db.flush()
    elif row.interval_seconds != max(1, interval_seconds):
        row.interval_seconds = max(1, interval_seconds)
    return row


def job_due(row: AutomationJobState, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    completed = _utc(row.last_completed_at)
    started = _utc(row.last_started_at)
    reference = completed or started
    if reference is None:
        return True
    return now >= reference + timedelta(seconds=max(1, int(row.interval_seconds or 1)))


def run_job_if_due(
    db: Session,
    job_key: str,
    interval_seconds: int,
    fn: Callable[[Session], Any],
) -> tuple[bool, Any | None]:
    now = datetime.now(timezone.utc)
    row = job_state(db, job_key, interval_seconds)
    if not job_due(row, now):
        db.commit()
        return False, None

    row.last_started_at = now
    row.last_status = "running"
    row.last_error = None
    db.commit()

    try:
        result = fn(db)
        row = db.scalar(select(AutomationJobState).where(AutomationJobState.job_key == job_key))
        if row is None:
            row = job_state(db, job_key, interval_seconds)
        row.last_completed_at = datetime.now(timezone.utc)
        row.last_status = "success"
        row.last_result = json.dumps(result, default=str)[:4000] if result is not None else None
        row.last_error = None
        row.run_count = int(row.run_count or 0) + 1
        db.commit()
        return True, result
    except Exception as exc:
        db.rollback()
        row = db.scalar(select(AutomationJobState).where(AutomationJobState.job_key == job_key))
        if row is None:
            row = job_state(db, job_key, interval_seconds)
        row.last_completed_at = datetime.now(timezone.utc)
        row.last_status = "failed"
        row.last_error = str(exc)[:4000]
        row.failure_count = int(row.failure_count or 0) + 1
        row.run_count = int(row.run_count or 0) + 1
        emit_realtime_event(
            db,
            "automation.job_failed",
            audience="platform_admins",
            entity_type="automation_job",
            entity_id=job_key,
            payload={"job_key": job_key, "error": str(exc)[:1000]},
        )
        db.commit()
        return True, {"failed": True, "error": str(exc)}


@router.get("/api/v1/admin/automation/jobs")
def list_automation_jobs(_: User = Depends(platform_admin), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(AutomationJobState).order_by(AutomationJobState.job_key)))
    now = datetime.now(timezone.utc)
    return [{
        "job_key": row.job_key,
        "interval_seconds": row.interval_seconds,
        "last_started_at": row.last_started_at,
        "last_completed_at": row.last_completed_at,
        "last_status": row.last_status,
        "last_result": row.last_result,
        "last_error": row.last_error,
        "run_count": row.run_count,
        "failure_count": row.failure_count,
        "due": job_due(row, now),
        "stalled": bool(
            row.last_status == "running"
            and _utc(row.last_started_at)
            and now - _utc(row.last_started_at) > timedelta(seconds=max(300, int(row.interval_seconds or 1) * 2))
        ),
    } for row in rows]


@router.post("/api/v1/admin/automation/jobs/{job_key}/run-now")
def queue_automation_job(
    job_key: str,
    admin: User = Depends(platform_admin),
    db: Session = Depends(get_db),
):
    row = db.scalar(select(AutomationJobState).where(AutomationJobState.job_key == job_key))
    if row is None:
        raise HTTPException(status_code=404, detail="Automation job not found")

    previous_status = row.last_status
    row.last_started_at = None
    row.last_completed_at = None
    row.last_status = "queued"
    row.last_error = None

    db.add(AuditLog(
        actor_user_id=admin.id,
        action="automation.job_queued",
        entity_type="automation_job",
        entity_id=job_key,
        detail=f"Manual run requested; previous status={previous_status}",
    ))
    emit_realtime_event(
        db,
        "automation.job_queued",
        audience="platform_admins",
        entity_type="automation_job",
        entity_id=job_key,
        payload={"job_key": job_key, "previous_status": previous_status},
    )
    db.commit()
    return {"job_key": job_key, "status": "queued", "due": True}


@router.get("/api/v1/admin/platform-health")
def platform_health(_: User = Depends(platform_admin), db: Session = Depends(get_db)):
    keys = [
        "health.backup.status",
        "health.backup.detail",
        "health.backup.checked_at",
    ]
    rows = list(db.scalars(select(SystemSetting).where(SystemSetting.key.in_(keys))))
    values = {row.key: row.value for row in rows}
    return {
        "backup": {
            "status": values.get("health.backup.status"),
            "detail": values.get("health.backup.detail"),
            "checked_at": values.get("health.backup.checked_at"),
        }
    }
