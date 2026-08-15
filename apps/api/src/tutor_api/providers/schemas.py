from pydantic import BaseModel, ConfigDict


class ModelCatalogItem(BaseModel):
    """The intentionally small, user-safe model catalog response."""

    model_config = ConfigDict(extra="forbid")

    id: str
    provider: str
    display_name: str
    price_summary: str
