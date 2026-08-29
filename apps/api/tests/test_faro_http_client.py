import httpx

from tutor_api.llm.http_client import FailoverTransport, create_faro_http_client


def test_failover_transport_retries_direct_when_proxy_cannot_connect() -> None:
    calls: list[str] = []

    def proxy_handler(request: httpx.Request) -> httpx.Response:
        calls.append("proxy")
        raise httpx.ConnectError("stale proxy", request=request)

    def direct_handler(_: httpx.Request) -> httpx.Response:
        calls.append("direct")
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(
        transport=FailoverTransport(
            primary=httpx.MockTransport(proxy_handler),
            fallback=httpx.MockTransport(direct_handler),
        )
    )

    response = client.post("https://faroapi.com/v1/chat/completions", json={"model": "test"})

    assert response.status_code == 200
    assert calls == ["proxy", "direct"]


def test_failover_transport_does_not_duplicate_completed_http_responses() -> None:
    calls: list[str] = []

    def proxy_handler(_: httpx.Request) -> httpx.Response:
        calls.append("proxy")
        return httpx.Response(503)

    def direct_handler(_: httpx.Request) -> httpx.Response:
        calls.append("direct")
        return httpx.Response(200)

    client = httpx.Client(
        transport=FailoverTransport(
            primary=httpx.MockTransport(proxy_handler),
            fallback=httpx.MockTransport(direct_handler),
        )
    )

    response = client.post("https://faroapi.com/v1/chat/completions", content=b"request")

    assert response.status_code == 503
    assert calls == ["proxy"]


def test_faro_client_uses_direct_transport_when_proxy_is_not_configured(
    monkeypatch,
) -> None:
    created_transports: list[dict[str, object]] = []

    class RecordingTransport(httpx.BaseTransport):
        def __init__(self, **options: object) -> None:
            created_transports.append(options)

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, request=request)

    monkeypatch.setattr("tutor_api.llm.http_client.httpx.HTTPTransport", RecordingTransport)

    client = create_faro_http_client(proxy_url="", timeout_seconds=60)
    response = client.get("https://faroapi.com/v1/models")
    client.close()

    assert response.status_code == 200
    assert created_transports == [{"retries": 2, "local_address": "0.0.0.0"}]


def test_faro_client_configures_proxy_with_safe_direct_failover(monkeypatch) -> None:
    created_transports: list[dict[str, object]] = []

    class RecordingTransport(httpx.BaseTransport):
        def __init__(self, **options: object) -> None:
            self.options = options
            created_transports.append(options)

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            if "proxy" in self.options:
                raise httpx.ConnectError("relay is down", request=request)
            return httpx.Response(200, request=request)

    monkeypatch.setattr("tutor_api.llm.http_client.httpx.HTTPTransport", RecordingTransport)

    client = create_faro_http_client(
        proxy_url="http://host.docker.internal:17897",
        timeout_seconds=180,
    )
    response = client.get("https://faroapi.com/v1/models")
    client.close()

    assert response.status_code == 200
    assert created_transports == [
        {"retries": 2, "local_address": "0.0.0.0"},
        {
            "proxy": "http://host.docker.internal:17897",
            "retries": 2,
            "local_address": "0.0.0.0",
        },
    ]
