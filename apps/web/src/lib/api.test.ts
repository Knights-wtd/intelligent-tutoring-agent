import { describe, expect, it, vi } from "vitest";

import { api } from "./api";

describe("api", () => {
  it("sends same-origin API requests with cookies included", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(null), { status: 401 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.me();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/me",
      expect.objectContaining({ credentials: "include" }),
    );
  });
});
