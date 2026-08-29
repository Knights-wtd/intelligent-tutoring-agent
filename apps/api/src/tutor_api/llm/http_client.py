"""Hardened HTTP client construction for Faro provider calls."""

from __future__ import annotations

import httpx


class FailoverTransport(httpx.BaseTransport):
    """Use a configured proxy first, then direct egress on connect failures.

    The fallback is deliberately limited to connection establishment failures.
    Once an HTTP response exists, retrying the POST through another route could
    duplicate a provider request and its billing side effects.
    """

    def __init__(
        self,
        *,
        primary: httpx.BaseTransport,
        fallback: httpx.BaseTransport,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        content = request.read()
        try:
            return self._primary.handle_request(_copy_request(request, content))
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError):
            return self._fallback.handle_request(_copy_request(request, content))

    def close(self) -> None:
        self._primary.close()
        self._fallback.close()


def create_faro_http_client(*, proxy_url: str, timeout_seconds: float) -> httpx.Client:
    """Create the shared Faro client used by both the API and ingestion worker."""

    direct_transport = httpx.HTTPTransport(retries=2, local_address="0.0.0.0")
    transport: httpx.BaseTransport = direct_transport
    if proxy_url:
        proxy_transport = httpx.HTTPTransport(
            proxy=proxy_url,
            retries=2,
            local_address="0.0.0.0",
        )
        transport = FailoverTransport(
            primary=proxy_transport,
            fallback=direct_transport,
        )

    return httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds)),
        trust_env=False,
    )


def _copy_request(request: httpx.Request, content: bytes) -> httpx.Request:
    return httpx.Request(
        method=request.method,
        url=request.url,
        headers=request.headers,
        content=content,
        extensions=dict(request.extensions),
    )
