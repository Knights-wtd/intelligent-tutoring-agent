from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from tutor_api.classrooms.schemas import (
    ClassroomMemberResponse,
    ClassroomResponse,
    CreateClassroomRequest,
    CreatedClassroomResponse,
    CreateInviteRequest,
    InviteResponse,
    JoinClassroomRequest,
    MemberUpdateRequest,
)
from tutor_api.classrooms.service import (
    create_classroom,
    create_invite,
    get_member_classroom,
    join_classroom,
    update_member,
)
from tutor_api.core.database import session_scope
from tutor_api.identity.router import CurrentUser, _session_factory
from tutor_api.spaces.schemas import SpaceResponse

router = APIRouter(prefix="/api/v1/classrooms", tags=["classrooms"])


def _response(classroom, space, membership) -> ClassroomResponse:
    return ClassroomResponse(
        id=classroom.id,
        name=classroom.name,
        space=SpaceResponse(id=space.id, kind=space.kind.value, name=space.name),
        membership=ClassroomMemberResponse(user_id=membership.user_id, role=membership.role.value),
    )


@router.post("", response_model=CreatedClassroomResponse, status_code=status.HTTP_201_CREATED)
def post_classroom(
    payload: CreateClassroomRequest, request: Request, current_user: CurrentUser
) -> CreatedClassroomResponse:
    with session_scope(_session_factory(request)) as session:
        classroom, space, membership, code = create_classroom(session, current_user, payload.name)
        return CreatedClassroomResponse(
            **_response(classroom, space, membership).model_dump(), invite_code=code
        )


@router.post("/join", response_model=ClassroomResponse)
def post_join(
    payload: JoinClassroomRequest, request: Request, current_user: CurrentUser
) -> ClassroomResponse:
    with session_scope(_session_factory(request)) as session:
        return _response(*join_classroom(session, current_user, payload.code))


@router.get("/{classroom_id}", response_model=ClassroomResponse)
def get_classroom(
    classroom_id: UUID, request: Request, current_user: CurrentUser
) -> ClassroomResponse:
    with session_scope(_session_factory(request)) as session:
        return _response(*get_member_classroom(session, current_user, classroom_id))


@router.patch("/{classroom_id}/members/{user_id}", response_model=ClassroomMemberResponse)
def patch_member(
    classroom_id: UUID,
    user_id: UUID,
    payload: MemberUpdateRequest,
    request: Request,
    response: Response,
    current_user: CurrentUser,
) -> ClassroomMemberResponse | Response:
    with session_scope(_session_factory(request)) as session:
        member = update_member(
            session, current_user, classroom_id, user_id, payload.role, payload.remove
        )
        if member is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        return ClassroomMemberResponse(user_id=member.user_id, role=member.role.value)


@router.post(
    "/{classroom_id}/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED
)
def post_invite(
    classroom_id: UUID,
    payload: CreateInviteRequest,
    request: Request,
    current_user: CurrentUser,
) -> InviteResponse:
    with session_scope(_session_factory(request)) as session:
        code, invite = create_invite(
            session, current_user, classroom_id, payload.expires_in_hours, payload.max_uses
        )
        return InviteResponse(code=code, expires_at=invite.expires_at, max_uses=invite.max_uses)
