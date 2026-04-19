"""
AutoHelp.uz - Pydantic Schemas
Data validation and serialization schemas for API and internal use.
"""
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


# ── User Schemas ──────────────────────────────────────────────────

class UserBase(BaseModel):
    telegram_id: int
    full_name: str
    phone: str
    language: str = "uz"


class UserCreate(UserBase):
    pass


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_blocked: bool = False
    created_at: datetime


# ── Master Schemas ────────────────────────────────────────────────

class MasterBase(BaseModel):
    telegram_id: int
    full_name: str
    phone: str


class MasterCreate(MasterBase):
    district_id: int | None = None


class MasterResponse(MasterBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    rating: float
    total_orders: int
    completed_orders: int
    rejected_orders: int
    is_active: bool
    created_at: datetime


# ── Staff Schemas ─────────────────────────────────────────────────

class StaffCreate(BaseModel):
    telegram_id: int
    full_name: str
    phone: str | None = None
    role: str = "dispatcher"


class StaffResponse(StaffCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_active: bool
    created_at: datetime


# ── Order Schemas ─────────────────────────────────────────────────

class OrderCreate(BaseModel):
    user_id: int
    problem_type: str
    latitude: float
    longitude: float
    description: str | None = None


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_uid: str
    user_id: int
    master_id: int | None
    problem_type: str
    description: str | None
    latitude: float
    longitude: float
    status: str
    payment_amount: float | None
    created_at: datetime
    completed_at: datetime | None


class OrderStatusUpdate(BaseModel):
    new_status: str
    changed_by_telegram_id: int | None = None
    changed_by_role: str | None = None
    note: str | None = None


# ── Payment Schemas ───────────────────────────────────────────────

class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    amount: float
    confirmed_by_dispatcher: bool
    created_at: datetime


# ── Review Schemas ────────────────────────────────────────────────

class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = None


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    user_id: int
    master_id: int
    rating: int
    comment: str | None
    created_at: datetime


# ── District Schemas ──────────────────────────────────────────────

class DistrictCreate(BaseModel):
    name_uz: str
    name_ru: str
    polygon: str | None = None


class DistrictResponse(DistrictCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_active: bool
    created_at: datetime


# ── Statistics Schemas ────────────────────────────────────────────

class DashboardStats(BaseModel):
    today_orders: int = 0
    weekly_orders: int = 0
    monthly_orders: int = 0
    today_completed: int = 0
    today_sum: float = 0.0
    monthly_sum: float = 0.0
    avg_rating: float = 0.0
    online_masters: int = 0
    total_users: int = 0
    active_orders: int = 0
    cancelled_rate: float = 0.0
