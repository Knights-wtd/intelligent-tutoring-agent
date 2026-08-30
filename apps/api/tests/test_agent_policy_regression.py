from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ACTIVE_FILES = (
    REPOSITORY_ROOT / ".env.example",
    REPOSITORY_ROOT / "compose.yaml",
    REPOSITORY_ROOT / "README.md",
    REPOSITORY_ROOT / "apps/api/src/tutor_api/core/config.py",
    REPOSITORY_ROOT / "apps/api/src/tutor_api/main.py",
    REPOSITORY_ROOT / "apps/api/src/tutor_api/tutor/router.py",
    REPOSITORY_ROOT / "apps/api/src/tutor_api/tutor/service.py",
)
FORBIDDEN = (
    "无教材" + "证据时禁止",
    "仅依据" + "教材",
    "TUTOR_" + "PROMPT_MAX_CHARACTERS",
    "TUTOR_" + "HISTORY_MESSAGES",
    "TUTOR_" + "KNOWLEDGE_SOURCES",
    "TUTOR_" + "KNOWLEDGE_BASE_LIMIT",
    "TUTOR_" + "KNOWLEDGE_SCOPE",
    "TUTOR_" + "WEB_SEARCH_ENABLED",
    "TUTOR_" + "WEB_SEARCH_LANGUAGE",
    "TUTOR_" + "WEB_SEARCH_MAX_RESULTS",
    "TUTOR_" + "WEB_SEARCH_TIMEOUT_SECONDS",
    "tutor_" + "prompt_max_characters",
    "tutor_" + "history_messages",
    "tutor_" + "knowledge_sources",
    "tutor_" + "knowledge_base_limit",
    "tutor_" + "knowledge_scope",
    "tutor_" + "web_search_enabled",
    "tutor_" + "web_search_language",
    "tutor_" + "web_search_max_results",
    "tutor_" + "web_search_timeout_seconds",
)


def _active_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in ACTIVE_FILES)


@pytest.mark.parametrize("forbidden", FORBIDDEN)
def test_removed_tutor_restrictions_do_not_exist_in_active_configuration_or_prompts(
    forbidden: str,
) -> None:
    assert forbidden not in _active_text()
