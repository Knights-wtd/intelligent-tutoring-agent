from fastapi import APIRouter, Request

from tutor_api.core.database import session_scope
from tutor_api.identity.router import CurrentUser, _session_factory
from tutor_api.providers.schemas import ModelCatalogItem
from tutor_api.providers.service import list_user_models

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@router.get("", response_model=list[ModelCatalogItem])
def get_model_catalog(request: Request, current_user: CurrentUser) -> list[ModelCatalogItem]:
    del current_user
    with session_scope(_session_factory(request)) as session:
        return list_user_models(session)
