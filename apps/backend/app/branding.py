import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import SystemSetting, Tenant, TenantSetting, User, UserRole
from .security import validate_token_user

router = APIRouter()
bearer = HTTPBearer(auto_error=False)
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", "/data/media"))
BRANDING_DIR = MEDIA_ROOT / "branding"
BRANDING_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_LOGOS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
NAVY = colors.HexColor("#070A45")
RED = colors.HexColor("#E31545")
LIGHT = colors.HexColor("#F5F6FA")
MUTED = colors.HexColor("#64748B")
BORDER = colors.HexColor("#E2E8F0")


def _setting(db: Session, key: str) -> SystemSetting | None:
    return db.scalar(select(SystemSetting).where(SystemSetting.key == key))


def _set(db: Session, key: str, value: str | None) -> None:
    row = _setting(db, key)
    if row:
        row.value = value
        row.encrypted = False
    else:
        db.add(SystemSetting(key=key, value=value, encrypted=False))


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked session") from exc


def super_admin(user: User = Depends(current_user)) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user


def logo_path(db: Session, tenant_id: int | None = None) -> Path | None:
    if tenant_id is not None:
        tenant = db.get(Tenant, tenant_id)
        if tenant and tenant.logo_url and tenant.logo_url.startswith("/media/"):
            relative = tenant.logo_url.removeprefix("/media/").lstrip("/")
            path = MEDIA_ROOT / relative
            if path.is_file():
                return path
    row = _setting(db, "branding.logo_filename")
    if not row or not row.value:
        return None
    path = BRANDING_DIR / Path(row.value).name
    return path if path.is_file() else None


def tenant_brand(db: Session, tenant_id: int | None = None) -> tuple[str, colors.Color, bool]:
    tenant = db.get(Tenant, tenant_id) if tenant_id is not None else None
    if not tenant:
        return "Meloli Airwaves", RED, True
    try:
        accent = colors.HexColor(tenant.accent_color or "#E31545")
    except Exception:
        accent = RED
    return tenant.name or tenant.facebook_page_name or "Advertising Portal", accent, tenant.slug == "meloli-airwaves"


@router.get("/api/v1/system/branding")
def branding_status(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    path = logo_path(db)
    return {"logo_configured": path is not None, "logo_url": f"/media/branding/{path.name}" if path else None}


@router.post("/api/v1/system/branding/logo", status_code=201)
async def upload_branding_logo(file: UploadFile = File(...), _: User = Depends(super_admin), db: Session = Depends(get_db)):
    content_type = (file.content_type or "").lower()
    extension = ALLOWED_LOGOS.get(content_type)
    if extension is None:
        raise HTTPException(status_code=415, detail="Logo must be PNG, JPEG or WebP")
    data = await file.read(3 * 1024 * 1024 + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Logo file is empty")
    if len(data) > 3 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Logo must be smaller than 3 MB")
    filename = "meloli-logo" + extension
    for old in BRANDING_DIR.glob("meloli-logo.*"):
        try:
            old.unlink()
        except OSError:
            pass
    destination = BRANDING_DIR / filename
    destination.write_bytes(data)
    _set(db, "branding.logo_filename", filename)
    db.commit()
    return {"logo_configured": True, "logo_url": f"/media/branding/{filename}"}


@router.get("/media/branding/{filename}")
def serve_branding(filename: str):
    if not filename or filename != Path(filename).name:
        raise HTTPException(status_code=404, detail="Branding asset not found")
    path = BRANDING_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Branding asset not found")
    from fastapi.responses import FileResponse
    return FileResponse(path)


def draw_header(pdf, db: Session, title: str, document_no: str, status_text: str | None = None, tenant_id: int | None = None):
    width, height = pdf._pagesize
    brand_name, accent, is_meloli = tenant_brand(db, tenant_id)
    pdf.setFillColor(NAVY)
    pdf.rect(0, height - 122, width, 122, fill=1, stroke=0)
    path = logo_path(db, tenant_id)
    if path:
        try:
            image = ImageReader(str(path))
            iw, ih = image.getSize()
            max_w, max_h = 116, 54
            scale = min(max_w / iw, max_h / ih)
            pdf.drawImage(image, 46, height - 86, width=iw * scale, height=ih * scale, mask="auto", preserveAspectRatio=True)
        except Exception:
            path = None
    if not path:
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 18)
        if is_meloli:
            pdf.drawString(46, height - 58, "MELOLI")
            pdf.setFillColor(accent)
            pdf.drawString(112, height - 58, "AIRWAVES")
            pdf.setFillColor(colors.white)
            pdf.setFont("Helvetica", 8)
            pdf.drawString(46, height - 73, "MEDIA & ADVERTISING")
        else:
            pdf.drawString(46, height - 58, brand_name[:30])
            pdf.setFillColor(accent)
            pdf.rect(46, height - 76, min(150, max(48, pdf.stringWidth(brand_name[:30], "Helvetica-Bold", 18))), 3, fill=1, stroke=0)
            pdf.setFillColor(colors.white)
            pdf.setFont("Helvetica", 8)
            pdf.drawString(46, height - 90, "ADVERTISING PORTAL")

    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 19)
    pdf.drawRightString(width - 46, height - 54, title.upper())
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(colors.HexColor("#C7CBDC"))
    pdf.drawRightString(width - 46, height - 72, document_no)
    if status_text:
        sw = pdf.stringWidth(status_text.upper(), "Helvetica-Bold", 8) + 22
        pdf.setFillColor(accent if status_text.upper() not in {"PAID", "SETTLED"} else colors.HexColor("#16A34A"))
        pdf.roundRect(width - 46 - sw, height - 101, sw, 19, 9, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawCentredString(width - 46 - sw / 2, height - 95, status_text.upper())


def draw_footer(pdf, db: Session | None = None, tenant_id: int | None = None, page_text: str | None = None):
    width, _ = pdf._pagesize
    brand_name = "Meloli Airwaves"
    tenant_footer = None
    support_email = None
    support_phone = None
    if db is not None:
        brand_name, _, _ = tenant_brand(db, tenant_id)
        if tenant_id is not None:
            rows = {
                row.key: row.value
                for row in db.scalars(
                    select(TenantSetting).where(
                        TenantSetting.tenant_id == tenant_id,
                        TenantSetting.key.in_([
                            "branding.document_footer",
                            "branding.support_email",
                            "branding.support_phone",
                        ]),
                    )
                )
            }
            tenant_footer = rows.get("branding.document_footer")
            support_email = rows.get("branding.support_email")
            support_phone = rows.get("branding.support_phone")
    text = page_text or tenant_footer or f"Generated by the {brand_name} Advertising Portal"
    contact = " · ".join(value for value in [support_email, support_phone] if value)
    if contact:
        text = f"{text} · {contact}"
    pdf.setStrokeColor(BORDER)
    pdf.line(46, 49, width - 46, 49)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.5)
    pdf.drawString(46, 34, text)
    pdf.drawRightString(width - 46, 34, brand_name)


def info_label(pdf, x: float, y: float, label: str, value: str, value_width: int = 54):
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawString(x, y, label.upper())
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(x, y - 14, str(value)[:value_width])
