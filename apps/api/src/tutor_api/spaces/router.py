from fastapi import APIRouter, Request

from tutor_api.core.database import session_scope
from tutor_api.identity.router import CurrentUser, _session_factory
from tutor_api.spaces.schemas import SpaceResponse
from tutor_api.spaces.service import list_spaces

router = APIRouter(prefix="/api/v1/spaces", tags=["spaces"])


@router.get("", response_model=list[SpaceResponse])
def get_spaces(request: Request, current_user: CurrentUser) -> list[SpaceResponse]:
    with session_scope(_session_factory(request)) as session:
        spaces = list_spaces(session, current_user)
        return [
            SpaceResponse(id=space.id, kind=space.kind.value, name=space.name) for space in spaces
        ]
