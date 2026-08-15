from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status

from tutor_api.billing.schemas import (
    BillingEntryResponse,
    BillingMeResponse,
    ManualRechargeRequest,
    RechargeResponse,
    ReversalRequest,
    ReversalResponse,
)
from tutor_api.billing.service import (
    RechargeAlreadyReversedError,
    billing_entries,
    create_manual_recharge,
    reverse_manual_recharge,
)
from tutor_api.core.database import session_scope
from tutor_api.identity.router import CurrentUser, PlatformAdmin

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["administration"])


def _session_factory(request: Request):
    factory = request.app.state.session_factory
    if factory is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return factory


@admin_router.post(
    "/recharges", response_model=RechargeResponse, status_code=status.HTTP_201_CREATED
)
def create_recharge(
    payload: ManualRechargeRequest, request: Request, admin: PlatformAdmin
) -> RechargeResponse:
    try:
        with session_scope(_session_factory(request)) as session:
            record = create_manual_recharge(
                session,
                user_id=payload.user_id,
                amount=payload.amount,
                external_reference=payload.external_reference,
                reason=payload.reason,
                created_by_user_id=admin.id,
            )
            result = RechargeResponse(
                id=record.id,
                amount=payload.amount.quantize(Decimal("0.00000001")),
                external_reference=record.external_reference,
                created_at=record.created_at,
            )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="充值记录冲突") from error
    return result


@admin_router.post(
    "/recharges/{recharge_record_id}/reverse",
    response_model=ReversalResponse,
    status_code=status.HTTP_201_CREATED,
)
def reverse_recharge(
    recharge_record_id: UUID, payload: ReversalRequest, request: Request, admin: PlatformAdmin
) -> ReversalResponse:
    try:
        with session_scope(_session_factory(request)) as session:
            entry = reverse_manual_recharge(
                session,
                recharge_record_id=recharge_record_id,
                reason=payload.reason,
                reversed_by_user_id=admin.id,
            )
            result = ReversalResponse(
                id=entry.id,
                amount=entry.amount,
                created_at=entry.created_at,
            )
    except LookupError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="充值记录不存在"
        ) from error
    except RechargeAlreadyReversedError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该充值已冲正") from error
    return result


@router.get("/me", response_model=BillingMeResponse)
def billing_me(
    request: Request,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BillingMeResponse:
    with session_scope(_session_factory(request)) as session:
        balance, currency, entries, total = billing_entries(
            session, current_user.id, limit=limit, offset=offset
        )
        return BillingMeResponse(
            balance=balance,
            currency=currency,
            entries=[
                BillingEntryResponse(
                    id=entry.id,
                    amount=entry.amount,
                    entry_type=entry.entry_type.value,
                    created_at=entry.created_at,
                )
                for entry in entries
            ],
            total=total,
            limit=limit,
            offset=offset,
        )
