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

  it("deletes an encoded knowledge base and accepts an empty 204 response", async () => {
    const json = vi.fn(() => {
      throw new Error("204 responses must not be parsed as JSON");
    });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204, json });
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(knowledgeApi.remove("kb/1", controller.signal)).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/knowledge-bases/kb%2F1",
      expect.objectContaining({
        method: "DELETE",
        credentials: "include",
        signal: controller.signal,
      }),
    );
    expect(json).not.toHaveBeenCalled();
  });

  it("uploads multipart data with an idempotency key and without overriding its content type", async () => {
    const payload = {
      document_id: "doc-1",
      document_version_id: "version-1",
      source_name: "chapter.md",
      created_at: "2026-08-18T00:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const upload = await knowledgeApi.upload(
      "kb/1",
      new File(["# chapter"], "chapter.md", { type: "text/markdown" }),
      "upload-key-1",
    );

    expect(upload).toEqual(payload);
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


  it("loads a knowledge graph with an encoded knowledge base id", async () => {
    const graph = {
      knowledge_base_id: "kb/1",
      nodes: [{ id: "node-1", title: "勾股定理", kind: "concept", source_pointers: ["page:42"] }],
      edges: [{ id: "edge-1", source_id: "node-1", target_id: "node-2", kind: "term", relation: "related_to", source_pointer: "page:42" }],
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(graph), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(knowledgeApi.graph("kb/1")).resolves.toEqual(graph);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/knowledge-bases/kb%2F1/graph",
      expect.objectContaining({ credentials: "include" }),
    );
  });
  it("loads the database-authoritative workspace and a note lazily", async () => {
    const workspace = {
      knowledge_base_id: "kb/1",
      documents: [],
      candidate_batch: null,
      notes: [],
    };
    const note = {
      id: "note/1",
      title: "Faro 配置",
      kind: "note",
      markdown: "# Faro 配置",
      source_markers: [],
      source_document_id: null,
      source_name: null,
      parent: null,
      children: [],
      updated_at: "2026-08-28T00:00:00Z",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(workspace), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(note), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(knowledgeApi.workspace("kb/1")).resolves.toEqual(workspace);
    await expect(knowledgeApi.note("kb/1", "note/1")).resolves.toEqual(note);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/knowledge-bases/kb%2F1/workspace",
      expect.objectContaining({ credentials: "include", cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/knowledge-bases/kb%2F1/notes/note%2F1",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("loads document processing status without reusing a cached response", async () => {
    const status = {
      document_id: "doc/1",
      document_version_id: "version/1",
      processing_state: "searchable",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(status), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      knowledgeApi.documentStatus("kb/1", "doc/1", "version/1", controller.signal),
    ).resolves.toEqual(status);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/knowledge-bases/kb%2F1/documents/doc%2F1/versions/version%2F1/status",
      expect.objectContaining({
        credentials: "include",
        cache: "no-store",
        signal: controller.signal,
      }),
    );
  });

  it("starts, loads, and confirms a review-only candidate batch", async () => {
    const batch = {
      id: "batch-1",
      document_id: "doc-1",
      document_version_id: "version-1",
      generation_number: 1,
      state: "needs_review",
      failure_code: null,
      notes: [],
      links: [],
      created_at: "2026-08-24T00:00:00Z",
      updated_at: "2026-08-24T00:00:00Z",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(batch), { status: 202 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(batch), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ...batch, state: "confirmed" }), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await knowledgeApi.startCandidateGeneration(
      "kb/1",
      "version-1",
      "candidate-key",
    );
    await knowledgeApi.candidateBatch("kb/1", "batch-1");
    await knowledgeApi.confirmCandidateBatch(
      "kb/1",
      "batch-1",
      ["note-1"],
      ["link-1"],
    );

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/knowledge-bases/kb%2F1/candidate-batches",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Idempotency-Key": "candidate-key" }),
        body: JSON.stringify({ document_version_id: "version-1" }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/knowledge-bases/kb%2F1/candidate-batches/batch-1",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/v1/knowledge-bases/kb%2F1/candidate-batches/batch-1/confirm",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          accepted_note_ids: ["note-1"],
          accepted_link_ids: ["link-1"],
        }),
      }),
    );
  });
});
