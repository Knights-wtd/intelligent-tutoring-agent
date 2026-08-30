from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VerifiedUsage(BaseModel):
    """Usage supplied by a provider adapter after it has been verified server-side."""

    provider_profile_id: UUID
    input_units: int = Field(ge=0)
    cached_input_units: int = Field(ge=0)
    output_units: int = Field(ge=0)
    verified: bool = False


class ReservationResult(BaseModel):
    id: UUID
    wallet_id: UUID
    request_id: str
    reserved_amount: Decimal
    state: str


class SettlementResult(BaseModel):
    reservation_id: UUID
    ledger_entry_id: UUID
    charged_amount: Decimal


class ReleaseResult(BaseModel):
    reservation_id: UUID
    released: bool


class ManualRechargeRequest(BaseModel):
    user_id: UUID
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=8)
    external_reference: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("external_reference", "reason")
    @classmethod
    def validate_non_blank_audit_fields(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("充值审计字段不能为空白")
        return value


class ReversalRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_non_blank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("冲正原因不能为空白")
        return value


class RechargeResponse(BaseModel):
    id: UUID
    amount: Decimal
    external_reference: str
    created_at: datetime | None


class ReversalResponse(BaseModel):
    id: UUID
    amount: Decimal
    created_at: datetime | None


class BillingEntryResponse(BaseModel):
    id: UUID
    amount: Decimal
    entry_type: str
    created_at: datetime | None


class BillingMeResponse(BaseModel):
    balance: Decimal
    currency: str
    entries: list[BillingEntryResponse]
    total: int
    limit: int
    offset: int
    payment_provider: str = "mock"


class RechargeOrderRequest(BaseModel):
    """Create a self-service gateway recharge order (1 积分 = 1 元)."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["mock", "alipay", "wechat"]
    amount: Decimal = Field(gt=0, decimal_places=2, max_digits=12)


class RechargeOrderResponse(BaseModel):
    id: UUID
    out_trade_no: str
    provider: str
    amount: Decimal
    state: str
    pay_url: str | None = None
    code_url: str | None = None
    mock_confirmable: bool = False
    created_at: datetime | None
    paid_at: datetime | None = None
