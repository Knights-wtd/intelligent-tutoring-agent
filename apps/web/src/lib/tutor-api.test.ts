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

describe("tutorApi legacy history", () => {
  it("performs only a credentialed, encoded read request", async () => {
    const signal = new AbortController().signal;
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(conversation)));
    vi.stubGlobal("fetch", fetchMock);

    await tutorApi.getConversation("kb/一", "conversation/二", signal);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/knowledge-bases/kb%2F%E4%B8%80/tutor/conversations/conversation%2F%E4%BA%8C",
      expect.objectContaining({
        credentials: "include",
        headers: expect.objectContaining({ Accept: "application/json" }),
        signal,
      }),
    );
    expect(Object.keys(tutorApi)).toEqual(["getConversation"]);
  });

  it("exposes only the response status for failed history reads", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("provider secret leaked", { status: 503 })),
    );

    const error = await tutorApi
      .getConversation("kb", "conversation")
      .catch((value: unknown) => value);

    expect(error).toBeInstanceOf(TutorApiError);
    expect(error).toMatchObject({
      status: 503,
      message: "Legacy Tutor history request failed",
    });
    expect(String(error)).not.toContain("provider secret leaked");
  });
});
