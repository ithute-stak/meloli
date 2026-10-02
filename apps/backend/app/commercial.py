from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AdvertiserSubscription, AuditLog, CorporateAccount, PromoCode, SubscriptionPlan, User, UserRole
from .security import decode_access_token

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class PromoWrite(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    description: str | None = Field(default=None, max_length=240)
    percent_off: float = Field(default=0, ge=0, le=100)
    fixed_off: float = Field(default=0, ge=0)
    max_uses: int | None = Field(default=None, ge=1)
    active: bool = True
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class CorporateWrite(BaseModel):
    credit_limit: float = Field(ge=0)
    billing_cycle_day: int = Field(default=28, ge=1, le=28)
    active: bool = True


class PlanWrite(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=3000)
    monthly_price: float = Field(ge=0)
    included_posts: int = Field(ge=1, le=500)
    active: bool = True


class SubscriptionAssign(BaseModel):
    user_id: int
    plan_id: int
    months: int = Field(default=1, ge=1, le=24)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        user_id = int(decode_access_token(credentials.credentials)["sub"])
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account unavailable")
    return user


def super_admin(user: User = Depends(current_user)) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user


def audit(db: Session, actor: User, action: str, entity_type: str, entity_id: int | str | None = None, detail: str | None = None) -> None:
    db.add(AuditLog(actor_user_id=actor.id, action=action, entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None, detail=detail))


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def promo_for_code(db: Session, code: str | None) -> PromoCode | None:
    if not code:
        return None
    promo = db.scalar(select(PromoCode).where(PromoCode.code == code.strip().upper()))
    if not promo or not promo.active:
        raise HTTPException(status_code=400, detail="Promotion code is invalid or inactive")
    now = datetime.now(timezone.utc)
    starts_at = as_utc(promo.starts_at)
    ends_at = as_utc(promo.ends_at)
    if starts_at and starts_at > now:
        raise HTTPException(status_code=400, detail="Promotion code is not active yet")
    if ends_at and ends_at < now:
        raise HTTPException(status_code=400, detail="Promotion code has expired")
    if promo.max_uses is not None and promo.uses >= promo.max_uses:
        raise HTTPException(status_code=400, detail="Promotion code usage limit has been reached")
    return promo


def discounted_amount(amount: float | Decimal, promo: PromoCode | None) -> Decimal:
    base = Decimal(str(amount))
    if not promo:
        return base.quantize(Decimal("0.01"))
    percentage = base * (Decimal(str(promo.percent_off or 0)) / Decimal("100"))
    fixed = Decimal(str(promo.fixed_off or 0))
    return max(Decimal("0.00"), base - percentage - fixed).quantize(Decimal("0.01"))


@router.get("/api/v1/commercial/my-account")
def my_commercial_account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    corporate = db.scalar(select(CorporateAccount).where(CorporateAccount.user_id == user.id))
    subscription = db.scalar(
        select(AdvertiserSubscription)
        .where(AdvertiserSubscription.user_id == user.id, AdvertiserSubscription.active.is_(True))
        .order_by(AdvertiserSubscription.period_end.desc())
    )
    plan = db.get(SubscriptionPlan, subscription.plan_id) if subscription else None
    return {
        "corporate": None if not corporate else {
            "active": corporate.active,
            "credit_limit": float(corporate.credit_limit),
            "credit_used": float(corporate.credit_used),
            "available_credit": max(0, float(corporate.credit_limit) - float(corporate.credit_used)),
            "billing_cycle_day": corporate.billing_cycle_day,
        },
        "subscription": None if not subscription else {
            "id": subscription.id,
            "plan": plan.name if plan else None,
            "plan_code": plan.code if plan else None,
            "period_start": subscription.period_start,
            "period_end": subscription.period_end,
            "remaining_posts": subscription.remaining_posts,
            "active": subscription.active and as_utc(subscription.period_end) >= datetime.now(timezone.utc),
        },
    }


@router.get("/api/v1/admin/promos")
def list_promos(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(PromoCode).order_by(PromoCode.created_at.desc())))
    return [{"id":p.id,"code":p.code,"description":p.description,"percent_off":float(p.percent_off),"fixed_off":float(p.fixed_off),"max_uses":p.max_uses,"uses":p.uses,"active":p.active,"starts_at":p.starts_at,"ends_at":p.ends_at} for p in rows]


@router.post("/api/v1/admin/promos", status_code=201)
def create_promo(payload: PromoWrite, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    code = payload.code.strip().upper()
    if db.scalar(select(PromoCode).where(PromoCode.code == code)):
        raise HTTPException(status_code=409, detail="Promotion code already exists")
    promo = PromoCode(code=code, description=payload.description, percent_off=payload.percent_off, fixed_off=payload.fixed_off, max_uses=payload.max_uses, active=payload.active, starts_at=payload.starts_at, ends_at=payload.ends_at)
    db.add(promo); db.flush(); audit(db,admin,"promo.created","promo_code",promo.id,code); db.commit(); db.refresh(promo)
    return {"id":promo.id,"code":promo.code,"active":promo.active}


@router.patch("/api/v1/admin/promos/{promo_id}")
def update_promo(promo_id: int, payload: PromoWrite, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    promo=db.get(PromoCode,promo_id)
    if not promo: raise HTTPException(status_code=404,detail="Promotion code not found")
    promo.code=payload.code.strip().upper(); promo.description=payload.description; promo.percent_off=payload.percent_off; promo.fixed_off=payload.fixed_off; promo.max_uses=payload.max_uses; promo.active=payload.active; promo.starts_at=payload.starts_at; promo.ends_at=payload.ends_at
    audit(db,admin,"promo.updated","promo_code",promo.id,promo.code); db.commit()
    return {"id":promo.id,"code":promo.code,"active":promo.active}


@router.put("/api/v1/admin/advertisers/{user_id}/corporate")
def set_corporate(user_id: int, payload: CorporateWrite, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    user=db.get(User,user_id)
    if not user or user.role != UserRole.ADVERTISER: raise HTTPException(status_code=404,detail="Advertiser not found")
    row=db.scalar(select(CorporateAccount).where(CorporateAccount.user_id==user_id))
    if row is None: row=CorporateAccount(user_id=user_id,credit_used=0); db.add(row)
    if Decimal(str(payload.credit_limit)) < Decimal(str(row.credit_used or 0)):
        raise HTTPException(status_code=400,detail="Credit limit cannot be below already used credit")
    row.credit_limit=payload.credit_limit; row.billing_cycle_day=payload.billing_cycle_day; row.active=payload.active
    db.flush(); audit(db,admin,"corporate_account.updated","user",user_id,f"Limit LSL {payload.credit_limit:.2f}"); db.commit()
    return {"user_id":user_id,"credit_limit":float(row.credit_limit),"credit_used":float(row.credit_used),"active":row.active,"billing_cycle_day":row.billing_cycle_day}


@router.get("/api/v1/admin/subscription-plans")
def list_plans(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    rows=list(db.scalars(select(SubscriptionPlan).order_by(SubscriptionPlan.created_at.desc())))
    return [{"id":p.id,"code":p.code,"name":p.name,"description":p.description,"monthly_price":float(p.monthly_price),"included_posts":p.included_posts,"active":p.active} for p in rows]


@router.post("/api/v1/admin/subscription-plans", status_code=201)
def create_plan(payload: PlanWrite, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    code=payload.code.strip().upper()
    if db.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code==code)): raise HTTPException(status_code=409,detail="Plan code already exists")
    plan=SubscriptionPlan(code=code,name=payload.name,description=payload.description,monthly_price=payload.monthly_price,included_posts=payload.included_posts,active=payload.active)
    db.add(plan);db.flush();audit(db,admin,"subscription_plan.created","subscription_plan",plan.id,code);db.commit();db.refresh(plan)
    return {"id":plan.id,"code":plan.code,"name":plan.name}


@router.post("/api/v1/admin/subscriptions", status_code=201)
def assign_subscription(payload: SubscriptionAssign, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    user=db.get(User,payload.user_id); plan=db.get(SubscriptionPlan,payload.plan_id)
    if not user or user.role != UserRole.ADVERTISER: raise HTTPException(status_code=404,detail="Advertiser not found")
    if not plan or not plan.active: raise HTTPException(status_code=404,detail="Active subscription plan not found")
    now=datetime.now(timezone.utc)
    for existing in db.scalars(select(AdvertiserSubscription).where(AdvertiserSubscription.user_id==user.id,AdvertiserSubscription.active.is_(True))):
        existing.active=False
    sub=AdvertiserSubscription(user_id=user.id,plan_id=plan.id,period_start=now,period_end=now+timedelta(days=30*payload.months),remaining_posts=plan.included_posts*payload.months,active=True)
    db.add(sub);db.flush();audit(db,admin,"subscription.assigned","user",user.id,f"{plan.code} x{payload.months}");db.commit();db.refresh(sub)
    return {"id":sub.id,"user_id":user.id,"plan_id":plan.id,"remaining_posts":sub.remaining_posts,"period_end":sub.period_end}
