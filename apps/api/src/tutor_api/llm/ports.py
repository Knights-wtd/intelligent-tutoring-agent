from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class LlmUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class LlmCompletion:
    text: str
    usage: LlmUsage
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class TutorChatMessage:
    role: Literal["user", "assistant"]
    content: str


class LlmProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class MarkdownLlmAdapter(Protocol):
    def complete_markdown(self, source_text: str) -> LlmCompletion: ...


class TutorChatAdapter(Protocol):
    def complete_tutor(self, messages: Sequence[TutorChatMessage]) -> LlmCompletion: ...
