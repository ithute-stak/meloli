from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class UserRole(StrEnum):
    ADVERTISER = "advertiser"
    REVIEWER = "reviewer"
    PUBLISHER = "publisher"
    SUPER_ADMIN = "super_admin"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    PAYMENT_PENDING = "payment_pending"
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    REJECTED = "rejected"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class PublicationStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160))
    business_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), default=UserRole.ADVERTISER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="advertiser", foreign_keys="Campaign.advertiser_id")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AdvertisingPackage(Base):
    __tablename__ = "advertising_packages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="LSL")
    posts_included: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="package")


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    advertiser_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("advertising_packages.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    caption: Mapped[str] = mapped_column(Text)
    media_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    destination_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    preferred_publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[CampaignStatus] = mapped_column(Enum(CampaignStatus, name="campaign_status"), default=CampaignStatus.DRAFT, index=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    facebook_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    facebook_post_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    advertiser: Mapped[User] = relationship(back_populates="campaigns", foreign_keys=[advertiser_id])
    package: Mapped[AdvertisingPackage] = relationship(back_populates="campaigns")
    payments: Mapped[list["Payment"]] = relationship(back_populates="campaign")
    publications: Mapped[list["PublicationAttempt"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="LSL")
    method: Mapped[str] = mapped_column(String(80), default="manual")
    reference: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    promo_code_id: Mapped[int | None] = mapped_column(ForeignKey("promo_codes.id"), nullable=True, index=True)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus, name="payment_status"), default=PaymentStatus.PENDING, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    campaign: Mapped[Campaign] = relationship(back_populates="payments")


class PublicationAttempt(Base):
    __tablename__ = "publication_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    status: Mapped[PublicationStatus] = mapped_column(Enum(PublicationStatus, name="publication_status"), default=PublicationStatus.PENDING, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    external_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_post_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    campaign: Mapped[Campaign] = relationship(back_populates="publications")


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user: Mapped[User] = relationship(back_populates="notifications")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(160), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemSetting(Base):
    __tablename__ = "system_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CampaignPerformance(Base):
    __tablename__ = "campaign_performance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), unique=True, index=True)
    impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reach: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engaged_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reactions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CampaignPerformanceSnapshot(Base):
    __tablename__ = "campaign_performance_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reach: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engaged_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reactions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True, index=True)
    subject: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[TicketStatus] = mapped_column(Enum(TicketStatus, name="ticket_status"), default=TicketStatus.OPEN, index=True)
    staff_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PromoCode(Base):
    __tablename__ = "promo_codes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(240), nullable=True)
    percent_off: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    fixed_off: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CorporateAccount(Base):
    __tablename__ = "corporate_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    credit_limit: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    credit_used: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    billing_cycle_day: Mapped[int] = mapped_column(Integer, default=28)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    monthly_price: Mapped[float] = mapped_column(Numeric(12, 2))
    included_posts: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdvertiserSubscription(Base):
    __tablename__ = "advertiser_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    remaining_posts: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id"), index=True)
    channel: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CorporateSettlement(Base):
    __tablename__ = "corporate_settlements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corporate_account_id: Mapped[int] = mapped_column(ForeignKey("corporate_accounts.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(80), default="bank_transfer")
    reference: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    recorded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CorporateInvoice(Base):
    __tablename__ = "corporate_invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corporate_account_id: Mapped[int] = mapped_column(ForeignKey("corporate_accounts.id"), index=True)
    invoice_number: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    period_key: Mapped[str] = mapped_column(String(7), index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    amount_paid: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="LSL")
    status: Mapped[str] = mapped_column(String(32), default="issued", index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefundRequest(Base):
    __tablename__ = "refund_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="requested", index=True)
    staff_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class CorporateInvoiceLine(Base):
    __tablename__ = "corporate_invoice_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("corporate_invoices.id"), index=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), unique=True, index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CorporateCreditNote(Base):
    __tablename__ = "corporate_credit_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    credit_note_number: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    corporate_account_id: Mapped[int] = mapped_column(ForeignKey("corporate_accounts.id"), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("corporate_invoices.id"), nullable=True, index=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), index=True)
    refund_request_id: Mapped[int | None] = mapped_column(ForeignKey("refund_requests.id"), nullable=True, unique=True, index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    applied_to_invoice_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="LSL")
    reason: Mapped[str] = mapped_column(Text)
    issued_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
