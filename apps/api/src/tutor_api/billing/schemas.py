from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class VerifiedUsage(BaseModel):
    """Usage supplied by a provider adapter after it has been verified server-side."""

    provider_profile_id: UUID
    input_units: int = Field(ge=0)
    cached_input_units: int = Field(ge=0)
    output_units: int = Field(ge=0)
    verified: bool = True


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
