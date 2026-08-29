import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";

describe("API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("preserves the safe registration conflict reason returned by the API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "邮箱或用户名已被使用" }), {
          status: 409,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    await expect(
      api.register({
        email: "existing@example.com",
        username: "existing-user",
        password: "correct horse battery staple 9",
      }),
    ).rejects.toThrow("邮箱或用户名已被使用");
  });
});
