import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AgentSidecarReference } from "@/lib/agent-events";

import { AgentSidecarPreview } from "./agent-sidecar-preview";

function sidecar(
  overrides: Partial<AgentSidecarReference> = {},
): AgentSidecarReference {
  return {
    id: "sidecar-1",
    sha256: "abc123def456",
    size: 24,
    mediaType: "text/plain",
    ...overrides,
  };
}

function rangedResponse(
  body: string,
  range: string,
  contentType = "text/plain",
): Response {
  return new Response(body, {
    status: 206,
    headers: {
      "Content-Type": contentType,
      "Content-Range": range,
    },
  });
}

describe("AgentSidecarPreview", () => {
  it("loads text by Range, shows size/hash, and keeps loading until the full content is available", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce(rangedResponse("first-", "bytes 0-5/12"))
      .mockResolvedValueOnce(rangedResponse("second", "bytes 6-11/12"));
    const user = userEvent.setup();

    render(
      <AgentSidecarPreview
        chunkSize={6}
        load={load}
        sidecar={sidecar({ size: 12 })}
      />,
    );

    expect(await screen.findByText("first-")).toBeVisible();
    expect(load).toHaveBeenNthCalledWith(
      1,
      sidecar({ size: 12 }),
      { end: 5, start: 0 },
      expect.any(AbortSignal),
    );
    expect(screen.getByText("已加载 6 / 12 bytes")).toBeVisible();
    expect(screen.getByText("SHA-256 abc123def456")).toBeVisible();
    expect(screen.queryByText(/完整内容已加载/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "加载更多" }));

    expect(await screen.findByText("first-second")).toBeVisible();
    expect(load).toHaveBeenNthCalledWith(
      2,
      sidecar({ size: 12 }),
      { end: 11, start: 6 },
      expect.any(AbortSignal),
    );
    expect(screen.getByText("完整内容已加载 · 12 bytes")).toBeVisible();
    expect(screen.queryByRole("button", { name: "加载更多" })).not.toBeInTheDocument();
  });

  it.each([
    ["application/json", '{"answer":42}', /"answer": 42/],
    ["text/x-diff", "-old\n+new", /-old/],
  ])("safely previews %s sidecars", async (mediaType, body, expected) => {
    const load = vi.fn().mockResolvedValue(
      rangedResponse(body, `bytes 0-${body.length - 1}/${body.length}`, mediaType),
    );

    render(
      <AgentSidecarPreview
        load={load}
        sidecar={sidecar({ mediaType, size: body.length })}
      />,
    );

    expect(await screen.findByText(expected)).toBeVisible();
  });

  it("renders HTML as inert text instead of injecting it", async () => {
    const html = '<img src=x onerror="alert(1)"><script>bad()</script>';
    const load = vi.fn().mockResolvedValue(
      rangedResponse(html, `bytes 0-${html.length - 1}/${html.length}`, "text/html"),
    );
    const { container } = render(
      <AgentSidecarPreview
        load={load}
        sidecar={sidecar({ mediaType: "text/html", size: html.length })}
      />,
    );

    expect(await screen.findByText(/<img src=x/)).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("HTML 以纯文本安全显示")).toBeVisible();
  });

  it("uses a bounded render window without claiming the loaded sidecar is truncated", async () => {
    const body = "0123456789ABCDEFGHIJ";
    const load = vi.fn().mockResolvedValue(
      rangedResponse(body, `bytes 0-${body.length - 1}/${body.length}`),
    );
    const user = userEvent.setup();

    render(
      <AgentSidecarPreview
        load={load}
        renderWindowBytes={10}
        sidecar={sidecar({ size: body.length })}
      />,
    );

    expect(await screen.findByText("0123456789")).toBeVisible();
    expect(screen.getByText("预览窗口 1–10 / 20 bytes")).toBeVisible();
    expect(screen.queryByText(/内容已截断/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下一预览窗口" }));
    expect(screen.getByText("ABCDEFGHIJ")).toBeVisible();
    expect(screen.getByText("预览窗口 11–20 / 20 bytes")).toBeVisible();
  });

  it("offers a full-content download and reports loading failures", async () => {
    const load = vi.fn().mockRejectedValue(new Error("network down"));

    render(
      <AgentSidecarPreview load={load} sidecar={sidecar()} />,
    );

    const download = screen.getByRole("link", { name: "下载完整内容" });
    expect(download).toHaveAttribute(
      "href",
      "/api/v1/agent/sidecars/sidecar-1",
    );
    expect(download).toHaveAttribute("download");
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("network down"));
  });
});
