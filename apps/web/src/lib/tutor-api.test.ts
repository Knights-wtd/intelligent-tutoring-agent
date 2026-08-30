import { afterEach, describe, expect, it, vi } from "vitest";

import { TutorApiError, tutorApi } from "./tutor-api";

const conversation = {
  id: "conversation-1",
  knowledge_base_id: "kb /数学",
  title: "勾股定理",
  messages: [],
  created_at: "2026-08-25T00:00:00Z",
  updated_at: "2026-08-25T00:00:00Z",
};

afterEach(() => vi.unstubAllGlobals());

describe("tutorApi", () => {
  it("uses credentialed JSON requests and forwards signals for status and create", async () => {
    const signal = new AbortController().signal;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ configured: true, model: "faro-mini" })))
      .mockResolvedValueOnce(new Response(JSON.stringify(conversation)));
    vi.stubGlobal("fetch", fetchMock);

    await tutorApi.status(signal);
    await tutorApi.createConversation("kb /数学", "解释勾股定理", signal);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v1/tutor/status", expect.objectContaining({ credentials: "include", signal }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/v1/knowledge-bases/kb%20%2F%E6%95%B0%E5%AD%A6/tutor/conversations", expect.objectContaining({
      method: "POST",
      credentials: "include",
      headers: expect.objectContaining({ "Content-Type": "application/json" }),
      body: JSON.stringify({ prompt: "解释勾股定理" }),
      signal,
    }));
  });

  it("encodes both resource ids for get and send", async () => {
    const signal = new AbortController().signal;
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify(conversation))),
    );
    vi.stubGlobal("fetch", fetchMock);

    await tutorApi.getConversation("kb/一", "conversation/二", signal);
    await tutorApi.sendMessage("kb/一", "conversation/二", "继续", signal);

    const base = "/api/v1/knowledge-bases/kb%2F%E4%B8%80/tutor/conversations/conversation%2F%E4%BA%8C";
    expect(fetchMock).toHaveBeenNthCalledWith(1, base, expect.objectContaining({ credentials: "include", signal }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${base}/messages`, expect.objectContaining({ method: "POST", body: JSON.stringify({ prompt: "继续" }), signal }));
  });

  it("exposes only the response status for failed requests", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("provider secret leaked", { status: 503 })));

    const error = await tutorApi.status().catch((value: unknown) => value);

    expect(error).toBeInstanceOf(TutorApiError);
    expect(error).toMatchObject({ status: 503, message: "Tutor request failed" });
    expect(String(error)).not.toContain("provider secret leaked");
  });
});
