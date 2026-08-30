from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.exc import IntegrityError

from tutor_api.billing.gateways import (
    GatewayCallback,
    InvalidPaymentNotifyError,
    PaymentRequestError,
    mock_notification_fields,
)
from tutor_api.billing.schemas import (
    BillingEntryResponse,
    BillingMeResponse,
    ManualRechargeRequest,
    RechargeOrderRequest,
    RechargeOrderResponse,
    RechargeResponse,
    ReversalRequest,
    ReversalResponse,
)
from tutor_api.billing.service import (
    DuplicateExternalReferenceError,
    RechargeAlreadyReversedError,
    RechargeCannotBeReversedError,
    RechargeOrderAmountError,
    RechargeOrderNotFoundError,
    RechargeTargetUserNotFoundError,
    billing_entries,
    confirm_recharge_payment,
    create_manual_recharge,
    create_recharge_order,
    recharge_order_for_user,
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
    except RechargeTargetUserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在") from error
    except DuplicateExternalReferenceError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="外部流水号已被使用"
        ) from error
    except IntegrityError as error:
        if "external_reference" not in str(error.orig).casefold():
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="外部流水号已被使用"
        ) from error
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
    except RechargeCannotBeReversedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="充值余额已被使用"
        ) from error
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
            payment_provider=request.app.state.payment_gateway.provider,
        )


def _order_response(request: Request, order: object) -> RechargeOrderResponse:
    del request
    creation = order.gateway_creation or {}
    return RechargeOrderResponse(
        id=order.id,
        out_trade_no=order.out_trade_no,
        provider=order.provider.value,
        amount=order.amount,
        state=order.state.value,
        pay_url=creation.get("pay_url"),
        code_url=creation.get("code_url"),
        mock_confirmable=order.state.value == "pending" and creation.get("mode") == "mock",
        created_at=order.created_at,
        paid_at=order.paid_at,
    )


@router.post(
    "/recharge-orders",
    response_model=RechargeOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_recharge_order(
    payload: RechargeOrderRequest, request: Request, current_user: CurrentUser
) -> RechargeOrderResponse:
    gateway = request.app.state.payment_gateway
    if payload.provider != gateway.provider:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="支付渠道暂未开通",
        )
    try:
        with session_scope(_session_factory(request)) as session:
            order = create_recharge_order(
                session,
                user_id=current_user.id,
                provider=payload.provider,
                amount=payload.amount,
            )
            creation = gateway.create_payment(order)
            order.gateway_creation = {
                "mode": creation.mode,
                "pay_url": creation.pay_url,
                "code_url": creation.code_url,
            }
            session.flush()
            return _order_response(request, order)
    except RechargeOrderAmountError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    except PaymentRequestError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="支付渠道暂时不可用"
        ) from error


@router.get("/recharge-orders/{order_id}", response_model=RechargeOrderResponse)
def get_recharge_order(
    order_id: UUID, request: Request, current_user: CurrentUser
) -> RechargeOrderResponse:
    with session_scope(_session_factory(request)) as session:
        try:
            order = recharge_order_for_user(session, order_id, user_id=current_user.id)
        except RechargeOrderNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="充值订单不存在"
            ) from None
        return _order_response(request, order)


@router.post(
    "/recharge-orders/{order_id}/mock-confirm", response_model=RechargeOrderResponse
)
def post_mock_confirm_recharge_order(
    order_id: UUID, request: Request, current_user: CurrentUser
) -> RechargeOrderResponse:
    """Local-only simulated cashier: runs the real crediting path without money.

    Available exclusively while PAYMENT_PROVIDER=mock, and only for the order's
    own user, so CI and local demos exercise the same code the gateway notify
    would trigger.
    """

    gateway = request.app.state.payment_gateway
    if gateway.provider != "mock":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="充值订单不存在"
        )
    with session_scope(_session_factory(request)) as session:
        try:
            order = recharge_order_for_user(session, order_id, user_id=current_user.id)
        except RechargeOrderNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="充值订单不存在"
            ) from None
        fields = mock_notification_fields(order)
        try:
            notification = gateway.verify_notify(
                GatewayCallback(headers={}, body=b"", form=fields)
            )
        except InvalidPaymentNotifyError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
            ) from error
        confirm_recharge_payment(
            session,
            out_trade_no=notification.out_trade_no,
            gateway_trade_no=notification.trade_no,
            paid_amount=notification.total_amount,
            notify_payload=notification.payload(),
        )
        session.flush()
        return _order_response(request, order)


@router.post("/payments/alipay/notify", response_class=PlainTextResponse)
async def post_alipay_notify(request: Request) -> PlainTextResponse:
    """Public gateway callback. Signature-verified; responds ``success`` per spec.

    Unauthenticated by design — Alipay servers post here. Anything that fails
    verification returns 400 so the gateway retries; anything verified is
    acknowledged with ``success`` (the plain-text body Alipay requires) even
    when no crediting happens, so retried notifications do not loop forever.
    """

    form = await request.form()
    fields = {str(key): str(value) for key, value in form.items()}
    gateway = request.app.state.payment_gateway
    if gateway.provider != "alipay":
        return PlainTextResponse("failure", status_code=status.HTTP_400_BAD_REQUEST)
    try:
        notification = gateway.verify_notify(
            GatewayCallback(headers=dict(request.headers), body=await request.body(), form=fields)
        )
    except InvalidPaymentNotifyError:
        return PlainTextResponse("failure", status_code=status.HTTP_400_BAD_REQUEST)
    if not notification.paid:
        return PlainTextResponse("success")
    try:
        with session_scope(_session_factory(request)) as session:
            confirm_recharge_payment(
                session,
                out_trade_no=notification.out_trade_no,
                gateway_trade_no=notification.trade_no,
                paid_amount=notification.total_amount,
                notify_payload=notification.payload(),
            )
    except RechargeOrderNotFoundError:
        return PlainTextResponse("failure", status_code=status.HTTP_400_BAD_REQUEST)
    return PlainTextResponse("success")


@router.post("/payments/wechat/notify")
async def post_wechat_notify(request: Request) -> JSONResponse:
    """Public WeChat Pay v3 callback; responds with the v3 acknowledgment JSON.

    Unauthenticated by design — WeChat Pay servers post here. The signature is
    verified against the platform certificate named by ``Wechatpay-Serial`` and
    the resource is decrypted with the APIv3 key inside the gateway. A 2xx body
    ``{"code": "SUCCESS"}`` stops retries; any failure returns ``FAIL`` so
    WeChat Pay retries (safe: crediting is idempotent and rejects mismatches).
    """

    gateway = request.app.state.payment_gateway
    if gateway.provider != "wechat":
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"code": "FAIL", "message": "channel not active"},
        )
    body = await request.body()
    try:
        notification = gateway.verify_notify(
            GatewayCallback(headers=dict(request.headers), body=body, form={})
        )
    except InvalidPaymentNotifyError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"code": "FAIL", "message": "signature verification failed"},
        )
    if not notification.paid:
        return JSONResponse(content={"code": "SUCCESS", "message": "成功"})
    try:
        with session_scope(_session_factory(request)) as session:
            confirm_recharge_payment(
                session,
                out_trade_no=notification.out_trade_no,
                gateway_trade_no=notification.trade_no,
                paid_amount=notification.total_amount,
                notify_payload=notification.payload(),
            )
    except RechargeOrderNotFoundError:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"code": "FAIL", "message": "order not found"},
        )
    return JSONResponse(content={"code": "SUCCESS", "message": "成功"})
