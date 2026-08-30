from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx

from tutor_api.agent.schemas import (
    RuntimeForkResponse,
    RuntimeHealth,
    RuntimeStartRequest,
    RuntimeStartResponse,
)


class RuntimeErrorBase(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 503) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class RuntimeUnavailable(RuntimeErrorBase):
    pass


class RuntimeRejected(RuntimeErrorBase):
    pass


class RuntimeClient:
    def __init__(self, client: httpx.AsyncClient, settings: Any) -> None:
        self._client = client
        self._base_url = str(
            getattr(settings, "agent_runtime_url", "http://127.0.0.1:8765")
        ).rstrip("/")
        parsed = httpx.URL(self._base_url)
        if parsed.host not in {"127.0.0.1", "::1", "localhost", "host.docker.internal"}:
            raise ValueError("agent_runtime_url_must_be_loopback")
        token = getattr(settings, "agent_runtime_token", "")
        getter = getattr(token, "get_secret_value", None)
        raw = getter() if getter else str(token)
        self._headers = {"Authorization": f"Bearer {raw}", "Cache-Control": "no-store"}
        self._timeout = float(getattr(settings, "agent_runtime_timeout_seconds", 30.0))

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        workspace_capability: str | None = None,
    ) -> dict[str, Any]:
        headers = dict(self._headers)
        if request_id:
            headers["X-Request-ID"] = request_id
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if workspace_capability:
            headers["X-Workspace-Capability"] = workspace_capability
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
            if response.status_code == 204:
                return {}
            try:
                data = response.json()
            except ValueError as error:
                raise RuntimeRejected("runtime_response_invalid", status_code=502) from error
            if not isinstance(data, dict):
                raise RuntimeRejected("runtime_response_invalid", status_code=502)
            return data
        except (httpx.ConnectError, httpx.TimeoutException) as error:
            raise RuntimeUnavailable("runtime_unavailable") from error
        except httpx.HTTPStatusError as error:
            code = "runtime_rejected"
            try:
                body = error.response.json()
                if isinstance(body, dict):
                    candidate = body.get("code")
                    if not isinstance(candidate, str):
                        nested = body.get("error")
                        candidate = nested.get("code") if isinstance(nested, dict) else None
                    if isinstance(candidate, str):
                        code = candidate
            except ValueError:
                pass
            raise RuntimeRejected(code, status_code=error.response.status_code) from error

    async def start_turn(
        self, payload: RuntimeStartRequest, *, request_id: str | None = None
    ) -> RuntimeStartResponse:
        return RuntimeStartResponse.model_validate(
            await self._request(
                "POST", "/v1/sessions/start", payload.model_dump(mode="json"), request_id=request_id
            )
        )

    async def stop(self, session_id: UUID, *, capability: str, idempotency_key: str) -> None:
        await self._request(
            "POST",
            f"/v1/sessions/{session_id}/stop",
            idempotency_key=idempotency_key,
            workspace_capability=capability,
        )

    async def resume(self, session_id: UUID) -> None:
        await self._request("POST", f"/v1/sessions/{session_id}/resume")

    async def rewind(
        self,
        session_id: UUID,
        checkpoint_id: str,
        *,
        capability: str,
        idempotency_key: str,
    ) -> None:
        await self._request(
            "POST",
            f"/v1/sessions/{session_id}/rewind",
            {"checkpoint_id": checkpoint_id},
            idempotency_key=idempotency_key,
            workspace_capability=capability,
        )

    async def fork(
        self,
        session_id: UUID,
        checkpoint_id: str,
        fork_session_id: UUID,
        *,
        capability: str,
        idempotency_key: str,
    ) -> RuntimeForkResponse:
        result = RuntimeForkResponse.model_validate(
            await self._request(
                "POST",
                f"/v1/sessions/{session_id}/fork",
                {
                    "checkpoint_id": checkpoint_id,
                    "fork_session_id": str(fork_session_id),
                },
                idempotency_key=idempotency_key,
                workspace_capability=capability,
            )
        )
        if result.session_id != fork_session_id:
            raise RuntimeRejected("runtime_fork_session_mismatch", status_code=502)
        return result

    async def health(self) -> RuntimeHealth:
        try:
            response = await self._client.get(
                f"{self._base_url}/v1/health",
                timeout=self._timeout,
                headers={"Cache-Control": "no-store"},
            )
            response.raise_for_status()
            return RuntimeHealth.model_validate(response.json())
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as error:
            raise RuntimeUnavailable("runtime_unavailable") from error

    async def proxy(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request(method, path, payload)

    async def get_sidecar(
        self, sidecar_id: UUID | str, *, range_header: str | None = None
    ) -> AsyncIterator[bytes]:
        headers = dict(self._headers)
        if range_header:
            headers["Range"] = range_header
        try:
            async with self._client.stream(
                "GET",
                f"{self._base_url}/v1/sidecars/{sidecar_id}",
                headers=headers,
                timeout=self._timeout,
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk
        except (httpx.ConnectError, httpx.TimeoutException) as error:
            raise RuntimeUnavailable("runtime_unavailable") from error
