import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AgentToolView } from "@/lib/agent-events";

import { AgentToolCard } from "./agent-tool-card";

function tool(
  kind: string,
  overrides: Partial<AgentToolView> = {},
): AgentToolView {
  return {
    id: `tool-${kind}`,
    turnId: "turn-parent",
    name: kind,
    kind,
    state: "running",
    input: {},
    payload: {},
    ...overrides,
  };
}

describe("AgentToolCard", () => {
  it.each([
    "bash",
    "read",
    "write",
    "edit",
    "move",
    "delete",
    "web_search",
    "web_fetch",
    "mcp",
    "skill",
    "subagent",
  ])("renders %s lifecycle without approval UI", (toolKind) => {
    render(<AgentToolCard tool={tool(toolKind)} />);

    expect(screen.getByTestId(`agent-tool-${toolKind}`)).toBeVisible();
    expect(screen.getByText("运行中")).toBeVisible();
    expect(screen.queryByText(/批准执行|允许一次|拒绝/)).not.toBeInTheDocument();
  });

  it("renders progress, completion duration, and failure details", () => {
    const { rerender } = render(
      <AgentToolCard
        tool={tool("read", {
          progress: "读取第 2 个分片",
          startedAt: "2026-08-28T00:00:00.000Z",
        })}
      />,
    );
    expect(screen.getByText("读取第 2 个分片")).toBeVisible();

    rerender(
      <AgentToolCard
        tool={tool("read", {
          state: "completed",
          output: "读取完成",
          startedAt: "2026-08-28T00:00:00.000Z",
          completedAt: "2026-08-28T00:00:01.250Z",
        })}
      />,
    );
    expect(screen.getByText("已完成")).toBeVisible();
    expect(screen.getByText("1.25 秒")).toBeVisible();
    expect(screen.getByText("读取完成")).toBeVisible();

    rerender(
      <AgentToolCard
        tool={tool("read", { state: "failed", error: "文件不存在" })}
      />,
    );
    expect(screen.getByText("失败")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("文件不存在");
  });

  it("renders file paths, move targets, and diffs for mutating tools", () => {
    render(
      <>
        <AgentToolCard
          tool={tool("write", {
            input: { path: "notes/new.md", content: "new text" },
            payload: { diff: "+new text" },
          })}
        />
        <AgentToolCard
          tool={tool("edit", {
            input: { path: "notes/edit.md" },
            payload: { diff: "-old\n+new" },
          })}
        />
        <AgentToolCard
          tool={tool("move", {
            input: { source: "notes/old.md", destination: "archive/new.md" },
          })}
        />
        <AgentToolCard tool={tool("delete", { input: { path: "trash.md" } })} />
      </>,
    );

    expect(screen.getByText("notes/new.md")).toBeVisible();
    expect(screen.getByText("notes/edit.md")).toBeVisible();
    expect(screen.getByText("notes/old.md → archive/new.md")).toBeVisible();
    expect(screen.getByText("trash.md")).toBeVisible();
    expect(screen.getByText("+new text")).toBeVisible();
    expect(screen.getByText(/-old/)).toBeVisible();
  });

  it("renders Bash command, cwd, streaming output, and exit code", () => {
    const { rerender } = render(
      <AgentToolCard
        tool={tool("bash", {
          input: { command: "pnpm test", cwd: "E:/workspace" },
          progress: "PASS first.test.ts",
        })}
      />,
    );

    const running = screen.getByTestId("agent-tool-bash");
    expect(within(running).getByText("pnpm test")).toBeVisible();
    expect(within(running).getByText("E:/workspace")).toBeVisible();
    expect(within(running).getByText("PASS first.test.ts")).toBeVisible();

    rerender(
      <AgentToolCard
        tool={tool("bash", {
          state: "completed",
          input: { command: "pnpm test", cwd: "E:/workspace" },
          output: { stdout: "2 tests passed", stderr: "", exit_code: 0 },
        })}
      />,
    );
    expect(screen.getByText("退出码 0")).toBeVisible();
    expect(screen.getByText("2 tests passed")).toBeVisible();
  });

  it("renders Web, MCP, Skill, and Subagent-specific metadata and parent links", async () => {
    const onOpenParent = vi.fn();
    const user = userEvent.setup();
    render(
      <>
        <AgentToolCard tool={tool("web_search", { input: { query: "Claude SDK" } })} />
        <AgentToolCard tool={tool("web_fetch", { input: { url: "https://example.com/docs" } })} />
        <AgentToolCard
          tool={tool("mcp", {
            input: { server: "filesystem", tool: "read_file" },
          })}
        />
        <AgentToolCard
          onOpenParent={onOpenParent}
          tool={tool("skill", {
            input: { skill: "tdd", parent_tool_call_id: "tool-parent" },
          })}
        />
        <AgentToolCard
          onOpenParent={onOpenParent}
          tool={tool("subagent", {
            input: { name: "reviewer", parent_tool_call_id: "tool-parent" },
            payload: { subagent_id: "sub-7" },
          })}
        />
      </>,
    );

    expect(screen.getByText("Claude SDK")).toBeVisible();
    expect(screen.getByText("https://example.com/docs")).toBeVisible();
    expect(screen.getByText("filesystem / read_file")).toBeVisible();
    expect(screen.getByText("Skill: tdd")).toBeVisible();
    expect(screen.getByText("Subagent: reviewer")).toBeVisible();
    expect(screen.getByText("sub-7")).toBeVisible();

    const parentButtons = screen.getAllByRole("button", { name: "打开父工具 tool-parent" });
    await user.click(parentButtons[0]);
    expect(onOpenParent).toHaveBeenCalledWith("tool-parent");
  });
});
