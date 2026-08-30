import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from tutor_api.agent.runtime_client import RuntimeClient, RuntimeRejected, RuntimeUnavailable
from tutor_api.agent.schemas import RuntimeStartRequest


def test_runtime_client_auth_and_start_contract() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == "Bearer runtime-token"
            return httpx.Response(
                200, json={"execution_id": "e", "native_session_id": "n", "accepted_sequence": 0}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = RuntimeClient(
                client,
                SimpleNamespace(
                    agent_runtime_url="http://127.0.0.1:8765",
                    agent_runtime_token=SecretStr("runtime-token"),
                    agent_runtime_timeout_seconds=1,
                ),
            )
            value = await runtime.start_turn(
                RuntimeStartRequest(
                    session_id=uuid4(),
                    turn_id=uuid4(),
                    input=[{"type": "text", "text": "hi"}],
                    workspace_roots=["C:/vault"],
                    provider="claude",
                    model="claude",
                    capability="token",
                    callback_url="http://127.0.0.1/callback",
                    idempotency_key="one",
                )
            )
            assert value.native_session_id == "n"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        ({"code": "runtime_busy"}, "runtime_busy"),
        ({"error": {"code": "runtime_busy"}}, "runtime_busy"),
    ],
)
def test_runtime_rejected_extracts_error_code_from_supported_response_shapes(
    body: dict[str, object], expected_code: str
) -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json=body, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = RuntimeClient(
                client,
                SimpleNamespace(
                    agent_runtime_url="http://127.0.0.1:8765", agent_runtime_token="token"
                ),
            )
            with pytest.raises(RuntimeRejected) as error:
                await runtime.proxy("POST", "/v1/test")

        assert error.value.code == expected_code
        assert error.value.status_code == 409

    asyncio.run(scenario())


def test_runtime_connect_error_has_stable_code() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = RuntimeClient(
                client,
                SimpleNamespace(
                    agent_runtime_url="http://127.0.0.1:8765", agent_runtime_token="token"
                ),
            )
            with pytest.raises(RuntimeUnavailable, match="runtime_unavailable"):
                await runtime.health()

    asyncio.run(scenario())


def test_runtime_url_must_be_loopback() -> None:
    with pytest.raises(ValueError, match="loopback"):
        RuntimeClient(
            httpx.AsyncClient(),
            SimpleNamespace(agent_runtime_url="https://example.com", agent_runtime_token="x"),
        )


def test_runtime_url_accepts_docker_host_gateway_alias() -> None:
    client = httpx.AsyncClient()
    try:
        RuntimeClient(
            client,
            SimpleNamespace(
                agent_runtime_url="http://host.docker.internal:8765",
                agent_runtime_token="x",
            ),
        )
    finally:
        asyncio.run(client.aclose())


def test_runtime_mutations_forward_capability_and_idempotency_contract() -> None:
    async def scenario() -> None:
        source_session_id = uuid4()
        fork_session_id = uuid4()
        expected = [
            (
                f"/v1/sessions/{source_session_id}/stop",
                "stop-capability",
                "stop-key",
                None,
            ),
            (
                f"/v1/sessions/{source_session_id}/rewind",
                "rewind-capability",
                "rewind-key",
                {"checkpoint_id": "checkpoint-rewind"},
            ),
            (
                f"/v1/sessions/{source_session_id}/fork",
                "fork-capability",
                "fork-key",
                {
                    "checkpoint_id": "checkpoint-fork",
                    "fork_session_id": str(fork_session_id),
                },
            ),
        ]

        async def handler(request: httpx.Request) -> httpx.Response:
            path, capability, idempotency_key, body = expected.pop(0)
            assert request.method == "POST"
            assert request.url.path == path
            assert request.headers["X-Workspace-Capability"] == capability
            assert request.headers["Idempotency-Key"] == idempotency_key
            if body is None:
                assert request.content in {b"", b"null"}
                return httpx.Response(204)
            assert json.loads(request.content) == body
            if request.url.path.endswith("/fork"):
                return httpx.Response(
                    201,
                    json={
                        "session_id": str(fork_session_id),
                        "native_session_id": "runtime-native-fork",
                    },
                )
            return httpx.Response(204)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = RuntimeClient(
                client,
                SimpleNamespace(
                    agent_runtime_url="http://127.0.0.1:8765",
                    agent_runtime_token="runtime-token",
                ),
            )
            await runtime.stop(
                source_session_id,
                capability="stop-capability",
                idempotency_key="stop-key",
            )
            await runtime.rewind(
                source_session_id,
                "checkpoint-rewind",
                capability="rewind-capability",
                idempotency_key="rewind-key",
            )
            forked = await runtime.fork(
                source_session_id,
                "checkpoint-fork",
                fork_session_id,
                capability="fork-capability",
                idempotency_key="fork-key",
            )

        assert forked.native_session_id == "runtime-native-fork"
        assert expected == []

    asyncio.run(scenario())
