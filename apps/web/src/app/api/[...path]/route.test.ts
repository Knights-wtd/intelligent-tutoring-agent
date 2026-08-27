import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

describe("API proxy route", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("forwards registration to the runtime API and preserves the session cookie", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8010/");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ user: { id: "user-1" } }), {
        status: 201,
        headers: {
          "content-type": "application/json",
          "set-cookie": "session=token; Path=/; HttpOnly; SameSite=Lax",
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const request = new Request("http://localhost:3000/api/v1/auth/register?source=web", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        email: "learner@example.com",
        username: "learner",
        password: "Correct horse battery staple 9",
      }),
    });

    const response = await POST(request, {
      params: Promise.resolve({ path: ["v1", "auth", "register"] }),
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const upstreamRequest = fetchMock.mock.calls[0]?.[0] as Request;
    expect(upstreamRequest.url).toBe("http://api:8010/api/v1/auth/register?source=web");
    expect(upstreamRequest.method).toBe("POST");
    expect(await upstreamRequest.json()).toMatchObject({ username: "learner" });
    expect(response.status).toBe(201);
    expect(response.headers.get("set-cookie")).toContain("session=token");
  });
});
