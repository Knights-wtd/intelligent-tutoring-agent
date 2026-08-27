import httpx

from tutor_api.knowledge import formula_evidence
from tutor_api.knowledge.formula_evidence import WikipediaFormulaEvidenceProvider


def test_formula_queries_use_nearby_textbook_heading_instead_of_only_symbols() -> None:
    source = (
        "[source:wireless.docx#block=12]\n"
        "\u81ea\u7531\u7a7a\u95f4\u4f20\u64ad\u6a21\u578b\n"
        "P_r(d)=(P_tG_tG_r)/(L(d))"
    )

    queries = formula_evidence.extract_formula_search_queries(source)

    assert queries
    assert "\u81ea\u7531\u7a7a\u95f4\u4f20\u64ad\u6a21\u578b" in queries[0]


def test_wikipedia_provider_returns_auditable_wikitext_formula_evidence() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        params = request.url.params
        if params.get("list") == "search":
            return httpx.Response(
                200,
                json={"query": {"search": [{"title": "Free-space path loss"}]}},
            )
        assert params.get("action") == "parse"
        return httpx.Response(
            200,
            json={
                "parse": {
                    "title": "Free-space path loss",
                    "wikitext": "<math>FSPL=(4\\pi d/\\lambda)^2</math>",
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    provider = WikipediaFormulaEvidenceProvider(
        http_client=client,
        language="en",
        max_queries=1,
        max_results_per_query=1,
    )

    evidence = provider.collect(
        "[source:wireless.docx#block=12]\nFree-space path loss\nP_r(d)=P_t/L(d)"
    )

    assert evidence == (
        {
            "title": "Free-space path loss",
            "url": "https://en.wikipedia.org/wiki/Free-space_path_loss",
            "source_type": "encyclopedia",
            "excerpt": "<math>FSPL=(4\\pi d/\\lambda)^2</math>",
        },
    )
    assert len(requests) == 2


def test_wikipedia_provider_fails_closed_when_internet_is_unavailable() -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    provider = WikipediaFormulaEvidenceProvider(  # noqa: F841
        http_client=httpx.Client(transport=httpx.MockTransport(fail)),
        language="en",
    )
