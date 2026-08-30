from uuid import UUID

from pydantic import BaseModel


class SpaceResponse(BaseModel):
    id: UUID
    kind: str
    name: str
