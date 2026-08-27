from tutor_api.knowledge.worker import make_markdown_draft_handler


def test_markdown_draft_handler_is_available_for_worker_registration() -> None:
    assert callable(make_markdown_draft_handler)