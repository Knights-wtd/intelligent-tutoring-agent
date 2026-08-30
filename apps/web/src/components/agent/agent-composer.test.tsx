import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AgentComposer } from "./agent-composer";

describe("AgentComposer", () => {
  it("submits a prompt longer than 500 characters without client truncation", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    const prompt = "知识库与网页联合推理。".repeat(100);

    render(
      <AgentComposer
        linkedContexts={[]}
        onSend={onSend}
        state="waiting_input"
      />,
    );

    const textbox = screen.getByRole("textbox", { name: "向 Agent 发送消息" });
    expect(textbox).not.toHaveAttribute("maxlength");
    fireEvent.change(textbox, { target: { value: prompt } });
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(onSend).toHaveBeenCalledWith({ text: prompt });
  });

  it("does not submit Enter while IME composition is active and sends after composition", async () => {
    const onSend = vi.fn();
    render(
      <AgentComposer
        linkedContexts={[]}
        onSend={onSend}
        state="waiting_input"
      />,
    );

    const textbox = screen.getByRole("textbox", { name: "向 Agent 发送消息" });
    fireEvent.change(textbox, { target: { value: "输入法内容" } });
    fireEvent.compositionStart(textbox);
    fireEvent.keyDown(textbox, { key: "Enter", code: "Enter", isComposing: true });
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.compositionEnd(textbox);
    fireEvent.keyDown(textbox, { key: "Enter", code: "Enter" });
    expect(onSend).toHaveBeenCalledWith({ text: "输入法内容" });
  });

  it("keeps Shift+Enter as a newline instead of submitting", () => {
    const onSend = vi.fn();
    render(
      <AgentComposer
        linkedContexts={[]}
        onSend={onSend}
        state="waiting_input"
      />,
    );

    const textbox = screen.getByRole("textbox", { name: "向 Agent 发送消息" });
    fireEvent.change(textbox, { target: { value: "第一行" } });
    fireEvent.keyDown(textbox, { key: "Enter", code: "Enter", shiftKey: true });

    expect(onSend).not.toHaveBeenCalled();
  });

  it("submits multiple linked contexts, attachments, skill and agent mention unchanged", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    const linkedContexts = [
      {
        knowledge_base_id: "kb-1",
        vault_file_id: "file-1",
        path: "课程/第一章.md",
        heading: "定义",
        selection: "完整选择内容，不预先截断",
      },
      {
        knowledge_base_id: "kb-1",
        vault_file_id: "file-2",
        path: "课程/第二章.md",
      },
    ];
    const attachments = [
      { id: "attachment-1", name: "图表.png", media_type: "image/png" },
      { id: "attachment-2", name: "原始数据.csv", media_type: "text/csv" },
    ];

    render(
      <AgentComposer
        agent="researcher"
        attachments={attachments}
        linkedContexts={linkedContexts}
        onSend={onSend}
        skill="deep-research"
        state="waiting_input"
      />,
    );

    expect(screen.getByText("课程/第一章.md · 定义")).toBeInTheDocument();
    expect(screen.getByText("课程/第二章.md")).toBeInTheDocument();
    expect(screen.getByText("图表.png")).toBeInTheDocument();
    expect(screen.getByText("原始数据.csv")).toBeInTheDocument();
    expect(screen.getByText("Skill: deep-research")).toBeInTheDocument();
    expect(screen.getByText("@researcher")).toBeInTheDocument();

    await user.type(screen.getByRole("textbox"), "请综合全部引用和附件");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(onSend).toHaveBeenCalledWith({
      text: "请综合全部引用和附件",
      linked_contexts: linkedContexts,
      attachments,
      skill: "deep-research",
      agent: "researcher",
    });
  });

  it("prefers user-visible context labels and never exposes raw context ids", () => {
    const knowledgeBaseId = "86d77e8b-74d0-4fea-ba1f-82f24a9c35e0";

    render(
      <AgentComposer
        linkedContexts={[
          { knowledge_base_id: knowledgeBaseId, label: "知识库：当前知识库" },
          {
            knowledge_base_id: "kb-1",
            vault_file_id: "file-1",
            source_name: "第一章.pdf",
            heading: "定义",
          },
          { knowledge_base_id: "kb-only", vault_file_id: "file-only" },
        ]}
        onSend={vi.fn()}
        state="waiting_input"
      />,
    );

    expect(screen.getByText("知识库：当前知识库")).toBeInTheDocument();
    expect(screen.getByText("第一章.pdf · 定义")).toBeInTheDocument();
    expect(screen.getByText("上下文 3")).toBeInTheDocument();
    expect(screen.queryByText(knowledgeBaseId)).not.toBeInTheDocument();
    expect(screen.queryByText("file-1")).not.toBeInTheDocument();
    expect(screen.queryByText("file-only")).not.toBeInTheDocument();
    expect(screen.queryByText("kb-only")).not.toBeInTheDocument();
  });
  it("shows Stop while running and delegates stopping", async () => {
    const user = userEvent.setup();
    const onStop = vi.fn();
    render(
      <AgentComposer
        linkedContexts={[]}
        onSend={vi.fn()}
        onStop={onStop}
        state="running"
      />,
    );

    expect(screen.queryByRole("button", { name: "发送" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "停止" }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it.each(["stopped", "failed"] as const)(
    "shows Resume while the session is %s and delegates resuming",
    async (state) => {
      const user = userEvent.setup();
      const onResume = vi.fn();
      render(
        <AgentComposer
          linkedContexts={[]}
          onResume={onResume}
          onSend={vi.fn()}
          state={state}
        />,
      );

      expect(screen.queryByRole("button", { name: "发送" })).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "继续" }));
      expect(onResume).toHaveBeenCalledTimes(1);
    },
  );
});
