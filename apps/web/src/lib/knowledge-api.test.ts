import { afterEach, describe, expect, it, vi } from "vitest";

import { KnowledgeApiError, knowledgeApi } from "./knowledge-api";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("knowledgeApi", () => {
  it("loads and creates space-scoped knowledge bases with cookie authentication", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "kb-1",
            space_id: "space-1",
            name: "数学教材",
            state: "ACTIVE",
            created_at: "2026-08-18T00:00:00Z",
            updated_at: "2026-08-18T00:00:00Z",
          }),
          { status: 201 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await knowledgeApi.list("space 1");
    await knowledgeApi.create("space 1", "数学教材");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/spaces/space%201/knowledge-bases",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/spaces/space%201/knowledge-bases",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({ name: "数学教材" }),
      }),
    );
  });

  it("uploads multipart data with an idempotency key and without overriding its content type", async () => {
    const payload = {
      document_id: "doc-1",
      document_version_id: "version-1",
      ingestion_job_id: "job-1",
      space_id: "space-1",
      knowledge_base_id: "kb-1",
      source_name: "chapter.md",
      version_number: 1,
      content_sha256: "abc",
      content_type: "text/markdown",
      document_state: "PROCESSING",
      version_state: "UPLOADED",
      job_state: "PENDING",
      created_at: "2026-08-18T00:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await knowledgeApi.upload(
      "kb/1",
      new File(["# chapter"], "chapter.md", { type: "text/markdown" }),
      "upload-key-1",
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/knowledge-bases/kb%2F1/documents");
    expect(init.credentials).toBe("include");
    expect(init.headers).toEqual({ "Idempotency-Key": "upload-key-1" });
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("searches with bounded results and opens an opaque cited page", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            results: [
              {
                excerpt: "勾股定理说明",
                citation: {
                  id: "cite_opaque-token",
                  source_name: "数学上册.pdf",
                  page_number: 42,
                },
              },
            ],
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response("第 42 页", {
          status: 206,
          headers: { "Content-Type": "text/plain; charset=utf-8" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await knowledgeApi.search("kb-1", "勾股定理", 20);
    const preview = await knowledgeApi.pagePreview("kb-1", "cite_opaque-token");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/knowledge-bases/kb-1/search",
      expect.objectContaining({
        credentials: "include",
        body: JSON.stringify({ query: "勾股定理", limit: 20 }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/knowledge-bases/kb-1/citations/cite_opaque-token/page",
      expect.objectContaining({
        credentials: "include",
        headers: { Range: "bytes=0-65535" },
      }),
    );
    expect(await preview.blob.text()).toBe("第 42 页");
  });

  it("does not expose provider response details through API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "s3://secret-key provider credentials" }), {
          status: 503,
        }),
      ),
    );

    const error = await knowledgeApi.list("space-1").catch((caught) => caught);

    expect(error).toBeInstanceOf(KnowledgeApiError);
    expect(error).toMatchObject({ status: 503 });
    expect(String(error)).not.toContain("secret-key");
    expect(String(error)).not.toContain("credentials");
  });
});
