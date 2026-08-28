import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeGraph } from "@/lib/knowledge-api";

import { KnowledgeGraphPanel } from "./knowledge-graph-panel";

const mockKnowledgeApi = vi.hoisted(() => ({ graph: vi.fn() }));

vi.mock("@/lib/knowledge-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/knowledge-api")>();
  return { ...actual, knowledgeApi: mockKnowledgeApi };
});

const graph: KnowledgeGraph = {
  knowledge_base_id: "kb-1",
  nodes: [
    {
      id: "node-pythagoras",
      note_id: "note-pythagoras",
      title: "勾股定理",
      kind: "concept",
      source_pointers: ["数学上册.pdf#page=42"],
    },
    {
      id: "node-triangle",
      note_id: "note-triangle",
      title: "直角三角形",
      kind: "section",
      source_pointers: ["数学上册.pdf#page=38", "讲义.md#直角三角形"],
    },
  ],
  edges: [
    {
      id: "edge-1",
      source_id: "node-pythagoras",
      target_id: "node-triangle",
      kind: "term",
      relation: "applies_to",
      source_pointer: "数学上册.pdf#page=42",
    },
  ],
};

beforeEach(() => {
  mockKnowledgeApi.graph.mockReset();
});

describe("KnowledgeGraphPanel", () => {
  it("shows loading, then an accessible SVG and equivalent keyboard node list", async () => {
    let resolveGraph!: (value: KnowledgeGraph) => void;
    mockKnowledgeApi.graph.mockReturnValue(
      new Promise<KnowledgeGraph>((resolve) => {
        resolveGraph = resolve;
      }),
    );

    render(<KnowledgeGraphPanel knowledgeBase={{ id: "kb-1", name: "七年级数学" }} />);

    expect(screen.getByRole("status")).toHaveTextContent("正在加载关联图…");
    await act(async () => resolveGraph(graph));

    expect(screen.getByRole("img", { name: "七年级数学关联图" })).toBeInTheDocument();
    const nodeList = screen.getByRole("list", { name: "关联图节点" });
    expect(within(nodeList).getAllByRole("button")).toHaveLength(2);
    expect(within(nodeList).getByRole("button", { name: "勾股定理" })).toBeEnabled();
    expect(screen.getByTestId("graph-edges").querySelectorAll("line")).toHaveLength(1);
  });

  it("exposes graph edge semantics as accessible relationships", async () => {
    mockKnowledgeApi.graph.mockResolvedValue(graph);
    render(<KnowledgeGraphPanel knowledgeBase={{ id: "kb-1", name: "七年级数学" }} />);

    const relationships = await screen.findByRole("list", { name: "关联关系" });
    const relationship = within(relationships).getByRole("listitem");

    expect(relationship).toHaveTextContent("勾股定理");
    expect(relationship).toHaveTextContent("直角三角形");
    expect(relationship).toHaveTextContent("applies_to");
    expect(relationship).toHaveTextContent("term");
    expect(relationship).toHaveTextContent("数学上册.pdf#page=42");
  });

  it("offers candidate review only when the optional empty-state callback is provided", async () => {
    const user = userEvent.setup();
    const onReviewCandidates = vi.fn();
    mockKnowledgeApi.graph.mockResolvedValue({ ...graph, nodes: [], edges: [] });

    const { rerender } = render(
      <KnowledgeGraphPanel
        knowledgeBase={{ id: "kb-empty", name: "空知识库" }}
        onReviewCandidates={onReviewCandidates}
      />,
    );

    expect(await screen.findByText("还没有已确认的知识节点。")) .toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "审核候选内容" }));
    expect(onReviewCandidates).toHaveBeenCalledTimes(1);

    rerender(<KnowledgeGraphPanel knowledgeBase={{ id: "kb-empty-2", name: "另一个空知识库" }} />);
    expect(await screen.findByText("还没有已确认的知识节点。")) .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "审核候选内容" })).not.toBeInTheDocument();
  });

  it("shows a non-abort failure and retries the graph request", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.graph
      .mockRejectedValueOnce(new Error("network unavailable"))
      .mockResolvedValueOnce(graph);

    render(<KnowledgeGraphPanel knowledgeBase={{ id: "kb-1", name: "七年级数学" }} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("关联图暂时无法加载，请重试。");
    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByRole("img", { name: "七年级数学关联图" })).toBeInTheDocument();
    expect(mockKnowledgeApi.graph).toHaveBeenCalledTimes(2);
  });

  it("filters the HTML node list without removing graph context", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.graph.mockResolvedValue(graph);
    render(<KnowledgeGraphPanel knowledgeBase={{ id: "kb-1", name: "七年级数学" }} />);
    await screen.findByRole("img", { name: "七年级数学关联图" });

    await user.type(screen.getByRole("searchbox", { name: "搜索节点" }), "勾股");

    const nodeList = screen.getByRole("list", { name: "关联图节点" });
    expect(within(nodeList).getByRole("button", { name: "勾股定理" })).toBeInTheDocument();
    expect(within(nodeList).queryByRole("button", { name: "直角三角形" })).not.toBeInTheDocument();
    expect(screen.getByTestId("graph-nodes").querySelectorAll("circle")).toHaveLength(2);
  });

  it("focuses a node, shows details, and fit view clears focus and resets the transform", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.graph.mockResolvedValue(graph);
    render(<KnowledgeGraphPanel knowledgeBase={{ id: "kb-1", name: "七年级数学" }} />);
    await screen.findByRole("img", { name: "七年级数学关联图" });

    await user.click(screen.getByRole("button", { name: "直角三角形" }));

    const details = screen.getByRole("region", { name: "节点详情" });
    expect(details).toHaveTextContent("直角三角形");
    expect(details).toHaveTextContent("section");
    expect(details).toHaveTextContent("数学上册.pdf#page=38");
    expect(details).toHaveTextContent("讲义.md#直角三角形");
    expect(screen.getByTestId("graph-viewport")).not.toHaveAttribute(
      "transform",
      "translate(0 0) scale(1)",
    );

    await user.click(screen.getByRole("button", { name: "适应视图" }));

    expect(screen.queryByRole("region", { name: "节点详情" })).not.toBeInTheDocument();
    expect(screen.getByTestId("graph-viewport")).toHaveAttribute(
      "transform",
      "translate(0 0) scale(1)",
    );
  });

  it("zooms with controls and the wheel, resets to 100%, and pans the canvas", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.graph.mockResolvedValue(graph);
    render(<KnowledgeGraphPanel knowledgeBase={{ id: "kb-1", name: "七年级数学" }} />);
    const canvas = await screen.findByTestId("graph-canvas");
    const viewport = screen.getByTestId("graph-viewport");

    expect(screen.getByText("100%")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "放大" }));
    expect(screen.getByText("120%")).toBeInTheDocument();
    expect(viewport).toHaveAttribute("transform", expect.stringContaining("scale(1.2)"));

    fireEvent.wheel(canvas, { deltaY: -100 });
    expect(screen.getByText("140%")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "100%" }));
    expect(viewport).toHaveAttribute("transform", "translate(0 0) scale(1)");

    fireEvent.pointerDown(canvas, { clientX: 20, clientY: 30, pointerId: 1 });
    fireEvent.pointerMove(canvas, { clientX: 70, clientY: 80, pointerId: 1 });
    fireEvent.pointerUp(canvas, { pointerId: 1 });
    expect(viewport).toHaveAttribute("transform", "translate(50 50) scale(1)");
  });

  it("routes a published graph node back to its knowledge note", async () => {
    const user = userEvent.setup();
    const onOpenNote = vi.fn();
    mockKnowledgeApi.graph.mockResolvedValue(graph);
    render(
      <KnowledgeGraphPanel
        knowledgeBase={{ id: "kb-1", name: "七年级数学" }}
        onOpenNote={onOpenNote}
      />,
    );
    await screen.findByRole("img", { name: "七年级数学关联图" });

    await user.click(screen.getByRole("button", { name: "勾股定理" }));

    expect(onOpenNote).toHaveBeenCalledWith("note-pythagoras");
  });

  it("aborts the old request, resets controls, and ignores its stale result", async () => {
    const user = userEvent.setup();
    let firstSignal: AbortSignal | undefined;
    let resolveFirst!: (value: KnowledgeGraph) => void;
    const currentGraph: KnowledgeGraph = {
      ...graph,
      knowledge_base_id: "kb-3",
      nodes: [{ id: "node-current", note_id: "note-current", title: "当前知识节点", kind: "concept", source_pointers: ["当前教材.pdf#page=9"] }],
      edges: [],
    };
    const staleGraph: KnowledgeGraph = {
      ...graph,
      knowledge_base_id: "kb-1",
      nodes: [{ id: "node-stale", note_id: "note-stale", title: "过期知识节点", kind: "concept", source_pointers: ["旧教材.pdf#page=1"] }],
      edges: [],
    };
    mockKnowledgeApi.graph
      .mockImplementationOnce((_id: string, signal?: AbortSignal) => {
        firstSignal = signal;
        return new Promise<KnowledgeGraph>((resolve) => {
          resolveFirst = resolve;
        });
      })
      .mockResolvedValueOnce({ ...graph, knowledge_base_id: "kb-2" })
      .mockResolvedValueOnce(currentGraph);

    const { rerender } = render(
      <KnowledgeGraphPanel knowledgeBase={{ id: "kb-1", name: "七年级数学" }} />,
    );
    rerender(<KnowledgeGraphPanel knowledgeBase={{ id: "kb-2", name: "八年级数学" }} />);

    expect(firstSignal?.aborted).toBe(true);
    expect(await screen.findByRole("img", { name: "八年级数学关联图" })).toBeInTheDocument();
    await user.type(screen.getByRole("searchbox", { name: "搜索节点" }), "勾股");
    await user.click(screen.getByRole("button", { name: "勾股定理" }));

    rerender(<KnowledgeGraphPanel knowledgeBase={{ id: "kb-3", name: "九年级数学" }} />);
    await screen.findByRole("button", { name: "当前知识节点" });
    expect(screen.getByRole("searchbox", { name: "搜索节点" })).toHaveValue("");
    expect(screen.queryByRole("region", { name: "节点详情" })).not.toBeInTheDocument();

    await act(async () => resolveFirst(staleGraph));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "当前知识节点" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "过期知识节点" })).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });
});
