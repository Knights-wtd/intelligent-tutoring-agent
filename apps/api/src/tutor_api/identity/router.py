import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tutor_api.core.database import session_scope
from tutor_api.core.security import hash_password, verify_password
from tutor_api.identity.models import User, UserSession
from tutor_api.identity.schemas import (
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    RegistrationRequest,
    RegistrationResponse,
    SpaceSummary,
    UserSummary,
)
from tutor_api.spaces.models import Space, SpaceKind

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
def _session_factory(request: Request):
    factory = request.app.state.session_factory
    if factory is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return factory


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.app_env == "production",
        max_age=settings.session_ttl_seconds,
        path="/",
    )


def _create_session(user_id, session, session_ttl_seconds: int) -> str:
    token = secrets.token_urlsafe(32)
    session.add(
        UserSession(
            user_id=user_id,
            token_digest=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(seconds=session_ttl_seconds),
        )
    )
    return token


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="认证失败")


def get_current_user(
    request: Request,
) -> User:
    session_token = request.cookies.get(request.app.state.settings.session_cookie_name)
    if not session_token:
        raise _unauthorized()
    digest = hashlib.sha256(session_token.encode()).hexdigest()
    with session_scope(_session_factory(request)) as session:
        user_session = session.scalar(select(UserSession).where(UserSession.token_digest == digest))
        if user_session is None or user_session.revoked_at is not None:
            raise _unauthorized()
        expires_at = user_session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            raise _unauthorized()
        user = session.get(User, user_session.user_id)
        if user is None:
            raise _unauthorized()
        session.expunge(user)
        return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "/register", response_model=RegistrationResponse, status_code=status.HTTP_201_CREATED
)
def register(
    payload: RegistrationRequest, request: Request, response: Response
) -> RegistrationResponse:
    try:
        with session_scope(_session_factory(request)) as session:
            user = User(
                email=payload.email,
                username=payload.username,
                password_hash=hash_password(payload.password),
            )
            session.add(user)
            session.flush()
            personal_space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="我的空间")
            session.add(personal_space)
            session.flush()
            token = _create_session(
                user.id, session, request.app.state.settings.session_ttl_seconds
            )
            result = RegistrationResponse(
                user=UserSummary(id=user.id, email=user.email, username=user.username),
                personal_space=SpaceSummary(
                    id=personal_space.id, kind=personal_space.kind.value, name=personal_space.name
                ),
            )
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="邮箱或用户名已被使用"
        ) from error
    _set_session_cookie(response, request, token)
    return result


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, response: Response) -> LoginResponse:
    with session_scope(_session_factory(request)) as session:
        user = session.scalar(select(User).where(User.email == payload.email))
        if user is None or not verify_password(payload.password, user.password_hash):
            raise _unauthorized()
        token = _create_session(user.id, session, request.app.state.settings.session_ttl_seconds)
        result = LoginResponse(
            user=UserSummary(id=user.id, email=user.email, username=user.username)
        )
    _set_session_cookie(response, request, token)
    return result


@router.get("/me", response_model=CurrentUserResponse)
def me(request: Request, current_user: CurrentUser) -> CurrentUserResponse:
    with session_scope(_session_factory(request)) as session:
        personal_space = session.scalar(
            select(Space).where(
                Space.owner_id == current_user.id,
                Space.kind == SpaceKind.PERSONAL,
            )
        )
        if personal_space is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        personal_space_summary = SpaceSummary(
            id=personal_space.id,
            kind=personal_space.kind.value,
            name=personal_space.name,
        )
    return CurrentUserResponse(
        user=UserSummary(
            id=current_user.id, email=current_user.email, username=current_user.username
        ),
        personal_space=personal_space_summary,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
) -> None:
    settings = request.app.state.settings
    session_token = request.cookies.get(settings.session_cookie_name)
    if session_token:
        digest = hashlib.sha256(session_token.encode()).hexdigest()
        with session_scope(_session_factory(request)) as session:
            user_session = session.scalar(
                select(UserSession).where(UserSession.token_digest == digest)
            )
            if user_session is not None and user_session.revoked_at is None:
                user_session.revoked_at = datetime.now(UTC)
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        samesite="lax",
        path="/",
    )
