from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


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


class ReversalRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


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
