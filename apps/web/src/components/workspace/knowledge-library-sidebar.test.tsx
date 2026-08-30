import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  MAX_KNOWLEDGE_BASE_NAME_CHARACTERS,
  type KnowledgeBase,
} from "@/lib/knowledge-api";

import { KnowledgeLibrarySidebar } from "./knowledge-library-sidebar";

const wireless: KnowledgeBase = {
  id: "wireless",
  space_id: "personal",
  name: "无线通信",
  state: "ready",
  created_at: "2026-08-24T00:00:00Z",
  updated_at: "2026-08-24T00:00:00Z",
};
const digital: KnowledgeBase = { ...wireless, id: "digital", name: "数字通信" };

function baseProps() {
  return {
    knowledgeBases: [wireless, digital],
    selectedKnowledgeBaseId: "wireless",
    onSelect: vi.fn(),
    onOpenGraph: vi.fn(),
    onCreate: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn().mockResolvedValue(undefined),
  };
}

describe("KnowledgeLibrarySidebar", () => {
  it("separates knowledge selection from the per-row graph action", async () => {
    const props = baseProps();
    const user = userEvent.setup();
    render(<KnowledgeLibrarySidebar {...props} />);

    await user.click(screen.getByRole("button", { name: "选择数字通信" }));
    expect(props.onSelect).toHaveBeenCalledWith("digital");
    expect(props.onOpenGraph).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "打开数字通信关联图" }));
    expect(props.onOpenGraph).toHaveBeenCalledWith(digital);
    expect(props.onSelect).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "选择无线通信" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("validates, trims, and submits a new knowledge base", async () => {
    const props = baseProps();
    const user = userEvent.setup();
    render(<KnowledgeLibrarySidebar {...props} />);

    await user.click(screen.getByText("新建知识库"));
    const input = screen.getByRole("textbox", { name: "知识库名称" });
    await user.click(screen.getByRole("button", { name: "创建知识库" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请输入知识库名称");

    await user.type(input, "x".repeat(MAX_KNOWLEDGE_BASE_NAME_CHARACTERS + 1));
    expect(input).toHaveAttribute(
      "maxlength",
      String(MAX_KNOWLEDGE_BASE_NAME_CHARACTERS),
    );
    await user.clear(input);
    await user.type(input, "  学习笔记  ");
    await user.click(screen.getByRole("button", { name: "创建知识库" }));

    expect(props.onCreate).toHaveBeenCalledWith("学习笔记");
    expect(input).toHaveValue("");
  });

  it("reports creation failure and allows retrying the form", async () => {
    const props = baseProps();
    props.onCreate.mockRejectedValueOnce(new Error("failed"));
    const user = userEvent.setup();
    render(<KnowledgeLibrarySidebar {...props} />);

    await user.click(screen.getByText("新建知识库"));
    await user.type(screen.getByRole("textbox", { name: "知识库名称" }), "学习笔记");
    await user.click(screen.getByRole("button", { name: "创建知识库" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("创建知识库失败");
    expect(screen.getByRole("button", { name: "创建知识库" })).toBeEnabled();
  });

  it("requires an inline name confirmation before permanently deleting", async () => {
    const props = baseProps();
    const user = userEvent.setup();
    render(<KnowledgeLibrarySidebar {...props} />);

    await user.click(screen.getByRole("button", { name: "删除无线通信" }));
    const confirmation = screen.getByRole("group", { name: "确认删除无线通信" });
    expect(confirmation).toHaveTextContent("无线通信");
    expect(confirmation).toHaveTextContent("不可撤销");
    const input = screen.getByRole("textbox", { name: "输入知识库名称无线通信以确认" });
    const confirmButton = screen.getByRole("button", { name: "永久删除无线通信" });
    expect(confirmButton).toBeDisabled();

    await user.type(input, "无线");
    expect(confirmButton).toBeDisabled();
    await user.type(input, "通信");
    expect(confirmButton).toBeEnabled();
    await user.click(confirmButton);

    expect(props.onDelete).toHaveBeenCalledWith(wireless);
    expect(screen.queryByRole("group", { name: "确认删除无线通信" })).not.toBeInTheDocument();
  });

  it("keeps the confirmation open and explains a running-task conflict", async () => {
    const props = baseProps();
    props.onDelete.mockRejectedValueOnce({ name: "KnowledgeApiError", status: 409 });
    const user = userEvent.setup();
    render(<KnowledgeLibrarySidebar {...props} />);

    await user.click(screen.getByRole("button", { name: "删除数字通信" }));
    await user.type(
      screen.getByRole("textbox", { name: "输入知识库名称数字通信以确认" }),
      "数字通信",
    );
    await user.click(screen.getByRole("button", { name: "永久删除数字通信" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "仍有文件处理或知识候选生成任务运行",
    );
    expect(screen.getByRole("group", { name: "确认删除数字通信" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "选择数字通信" })).toBeInTheDocument();
  });

  it("renders loading, empty, and failure states with a real retry", async () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <KnowledgeLibrarySidebar {...baseProps()} knowledgeBases={[]} isLoading />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("正在加载知识库");

    rerender(<KnowledgeLibrarySidebar {...baseProps()} knowledgeBases={[]} />);
    expect(screen.getByText("还没有知识库")).toBeInTheDocument();

    rerender(
      <KnowledgeLibrarySidebar
        {...baseProps()}
        error={new Error("failed")}
        knowledgeBases={[]}
        onRetry={onRetry}
      />,
    );
    const user = userEvent.setup();
    expect(screen.getByRole("alert")).toHaveTextContent("知识库加载失败");
    await user.click(screen.getByRole("button", { name: "重试加载知识库" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("renders only wired utility actions and invokes each callback", async () => {
    const callbacks = {
      onOpenImport: vi.fn(),
      onOpenDueReview: vi.fn(),
      onSwitchSpace: vi.fn(),
      onOpenClassroom: vi.fn(),
      onOpenSettings: vi.fn(),
    };
    const user = userEvent.setup();
    render(<KnowledgeLibrarySidebar {...baseProps()} {...callbacks} />);

    for (const label of ["导入教材", "待复习", "切换空间", "创建或加入班级", "设置"]) {
      await user.click(screen.getByRole("button", { name: label }));
    }
    for (const callback of Object.values(callbacks)) {
      expect(callback).toHaveBeenCalledOnce();
    }
  });
});