from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Provenance = Literal["source", "vault", "model", "web"]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

SEMANTIC_INDEX_PLANNER_SYSTEM_PROMPT = (
    "所有支持文件都已由确定性索引自动收录。你只负责判断语义分块、知识点、术语、别名、"
    "标签和关联，不得删除或静默忽略文件。你可以结合当前文件、其他已授权 Vault 内容、"
    "模型通用知识和公开 Web 来解释联系；不得虚构原文内容。凡不是原文直接支持的推断，"
    "都必须明确标记 provenance（vault/model/web）和 confidence。"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SemanticChunk(StrictModel):
    ordinal: int = Field(ge=0)
    heading: str | None = None
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    concepts: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_range(self) -> "SemanticChunk":
        if self.end <= self.start:
            raise ValueError("chunk end must be greater than start")
        if self.heading is not None and (not self.heading or "\x00" in self.heading):
            raise ValueError("chunk heading is invalid")
        return self


class SemanticConcept(StrictModel):
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    provenance: Provenance
    confidence: float = Field(ge=0, le=1)


class SemanticTerm(StrictModel):
    term: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    provenance: Provenance
    confidence: float = Field(ge=0, le=1)


class SemanticLink(StrictModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    relation: str = Field(min_length=1)
    provenance: Provenance
    confidence: float = Field(ge=0, le=1)


class SemanticIndexPlanPayload(StrictModel):
    schema_version: Literal["1.0"]
    source_hash: Sha256
    chunks: list[SemanticChunk]
    concepts: list[SemanticConcept]
    terms: list[SemanticTerm]
    links: list[SemanticLink]

    @model_validator(mode="after")
    def validate_graph(self) -> "SemanticIndexPlanPayload":
        ordinals = [chunk.ordinal for chunk in self.chunks]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("chunk ordinals must be unique")
        concept_names = {concept.name for concept in self.concepts}
        if len(concept_names) != len(self.concepts):
            raise ValueError("concept names must be unique")
        aliases = {alias for concept in self.concepts for alias in concept.aliases}
        references = concept_names | aliases
        for link in self.links:
            if link.source not in references or link.target not in references:
                raise ValueError("semantic link references an unknown concept")
        return self


def validate_semantic_index_plan(
    payload: object,
    *,
    expected_source_hash: str | None = None,
) -> SemanticIndexPlanPayload:
    plan = SemanticIndexPlanPayload.model_validate(payload)
    if expected_source_hash is not None and plan.source_hash != expected_source_hash:
        raise ValueError("semantic index plan source hash is stale")
    return plan
