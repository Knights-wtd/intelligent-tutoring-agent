import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest";

import {
  QuestionBankApiError,
  questionBankApi,
  type ReviewItem,
  type ReviewItemsResponse,
} from "./question-bank-api";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("questionBankApi", () => {
  it("loads encoded knowledge-base review items with supplied query options and cookie authentication", async () => {
    const payload = {
      items: [
        {
          question_id: "question-1",
          question_version_id: "question-version-1",
          question_type: "single_choice",
          prompt: "香农容量公式中的带宽如何影响信道容量？",
          attempted_at: "2026-08-25T08:00:00Z",
          correct: false,
          score_basis_points: 2500,
          error_type: "application",
          needs_review: true,
          review_due_at: "2026-08-26T08:00:00Z",
          review_interval_days: 1,
        },
      ],
      next_cursor: null,
    } satisfies ReviewItemsResponse;
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      questionBankApi.listReviewItems(
        "wireless/communications",
        { scope: "due", limit: 20 },
        controller.signal,
      ),
    ).resolves.toEqual(payload);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/knowledge-bases/wireless%2Fcommunications/review-items?scope=due&limit=20",
      expect.objectContaining({
        credentials: "include",
        signal: controller.signal,
      }),
    );
  });

  it("omits review query parameters that were not supplied", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await questionBankApi.listReviewItems("kb-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/knowledge-bases/kb-1/review-items",
      expect.objectContaining({ credentials: "include", signal: undefined }),
    );
  });

  it("supports passing an abort signal as the legacy second argument", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await questionBankApi.listReviewItems("kb-legacy", controller.signal);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/knowledge-bases/kb-legacy/review-items",
      expect.objectContaining({
        credentials: "include",
        signal: controller.signal,
      }),
    );
  });

  it("exposes only assessment error types from the review contract", () => {
    expectTypeOf<ReviewItem["error_type"]>().toEqualTypeOf<
      "none" | "metacognitive" | "application"
    >();
  });

  it("reports a stable status-only error for non-success responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "provider-token and private answer" }), {
          status: 503,
        }),
      ),
    );

    const error = await questionBankApi.listReviewItems("kb-1").catch((caught) => caught);

    expect(error).toBeInstanceOf(QuestionBankApiError);
    expect(error).toMatchObject({ status: 503 });
    expect(String(error)).not.toContain("provider-token");
    expect(String(error)).not.toContain("private answer");
  });
});
