import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .performance import router as performance_router
from .security import validate_token_user

router = APIRouter()
bearer = HTTPBearer(auto_error=False)
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", "/data/media"))
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
MAX_BYTES = int(os.getenv("MAX_MEDIA_BYTES", str(25 * 1024 * 1024)))
ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}


def authenticated_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid, expired or revoked session") from exc


@router.post("/api/v1/media", status_code=201)
async def upload_media(file: UploadFile = File(...), _: User = Depends(authenticated_user)):
    content_type = (file.content_type or "").lower()
    extension = ALLOWED_TYPES.get(content_type)
    if extension is None:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG, WebP, GIF, MP4, WebM and MOV media are supported")

    data = await file.read(MAX_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Media must be smaller than {MAX_BYTES // (1024 * 1024)} MB")

    filename = f"{uuid4().hex}{extension}"
    destination = MEDIA_ROOT / filename
    destination.write_bytes(data)
    return {"filename": filename, "content_type": content_type, "size": len(data), "url": f"/media/{filename}"}


@router.get("/media/{filename}")
def serve_media(filename: str):
    if not filename or filename != Path(filename).name:
        raise HTTPException(status_code=404, detail="Media not found")
    path = MEDIA_ROOT / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(path)


router.include_router(performance_router)
