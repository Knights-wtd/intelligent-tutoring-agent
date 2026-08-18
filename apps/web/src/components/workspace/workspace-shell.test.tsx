import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceShell } from "./workspace-shell";

const mockApi = vi.hoisted(() => ({
  models: vi.fn(),
  billingMe: vi.fn(),
}));

const mockKnowledgeApi = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  upload: vi.fn(),
  search: vi.fn(),
  pagePreview: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: mockApi }));
vi.mock("@/lib/knowledge-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/knowledge-api")>();
  return { ...actual, knowledgeApi: mockKnowledgeApi };
});

beforeEach(() => {
  mockApi.models.mockReset();
  mockApi.billingMe.mockReset();
  mockApi.models.mockResolvedValue([]);
  mockApi.billingMe.mockResolvedValue({ balance: "0", currency: "CNY", entries: [] });
  for (const mock of Object.values(mockKnowledgeApi)) mock.mockReset();
  mockKnowledgeApi.list.mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WorkspaceShell", () => {
  it("shows enabled models and simple balance without internal provider data", async () => {
    mockApi.models.mockResolvedValue([
      {
        id: "example-chat",
        display_name: "学习助手",
        provider: "example",
        price_summary: "按量计费",
      },
    ]);
    mockApi.billingMe.mockResolvedValue({ balance: "1.00500000", currency: "CNY", entries: [] });

    render(<WorkspaceShell />);

    expect(await screen.findByRole("option", { name: "学习助手" })).toBeInTheDocument();
    expect(screen.getByText("余额 ¥1.01")).toBeInTheDocument();
    expect(screen.queryByText(/API Key|Base URL/i)).not.toBeInTheDocument();
  });

  it("keeps the balance visible and retries only the model catalog when it is unavailable", async () => {
    const user = userEvent.setup();
    mockApi.models
      .mockRejectedValueOnce(new Error("not for display"))
      .mockResolvedValueOnce([
        {
          id: "example-chat",
          display_name: "学习助手",
          provider: "example",
          price_summary: "按量计费",
        },
      ]);
    mockApi.billingMe
      .mockResolvedValueOnce({ balance: "0", currency: "CNY", entries: [] })
      .mockResolvedValueOnce({ balance: "20.00", currency: "CNY", entries: [] });

    render(<WorkspaceShell />);

    expect(await screen.findByRole("status")).toHaveTextContent("模型暂时无法加载。");
    expect(screen.getByText("余额 ¥0.00")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试模型" }));

    expect(await screen.findByRole("option", { name: "学习助手" })).toBeInTheDocument();
    expect(screen.getByText("余额 ¥0.00")).toBeInTheDocument();
    expect(screen.queryByText("not for display")).not.toBeInTheDocument();
  });

  it("keeps the model choice visible and retries only the balance when it is unavailable", async () => {
    const user = userEvent.setup();
    mockApi.models.mockResolvedValueOnce([
      {
        id: "example-chat",
        display_name: "学习助手",
        provider: "example",
        price_summary: "按量计费",
      },
    ]);
    mockApi.billingMe
      .mockRejectedValueOnce(new Error("not for display"))
      .mockResolvedValueOnce({ balance: "20.00", currency: "CNY", entries: [] });

    render(<WorkspaceShell />);

    expect(await screen.findByRole("option", { name: "学习助手" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("余额暂时无法加载。");
    await user.click(screen.getByRole("button", { name: "重试余额" }));

    expect(await screen.findByText("余额 ¥20.00")).toBeInTheDocument();
    expect(screen.queryByText("not for display")).not.toBeInTheDocument();
  });

  it("renders authenticated personal and classroom spaces in the left rail", () => {
    render(
      <WorkspaceShell
        spaces={[
          { id: "personal", kind: "personal", name: "我的空间" },
          { id: "math", kind: "classroom", name: "七年级数学" },
        ]}
      />,
    );

    expect(screen.getByLabelText("个人空间")).toBeInTheDocument();
    expect(screen.getByLabelText("七年级数学")).toBeInTheDocument();
    expect(screen.getAllByRole("separator")).toHaveLength(2);
  });

  it("updates the content pane heading when a space is selected", async () => {
    const user = userEvent.setup();
    render(
      <WorkspaceShell
        spaces={[
          { id: "personal", kind: "personal", name: "我的空间" },
          { id: "math", kind: "classroom", name: "七年级数学" },
        ]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "个人空间" }));

    expect(screen.getByLabelText("当前空间内容")).toHaveTextContent("我的空间");
  });

  it("keeps spaces in the far-left rail and content in the second pane", () => {
    render(<WorkspaceShell />);

    const rail = screen.getByLabelText("空间切换");
    const tree = screen.getByLabelText("当前空间内容");
    expect(rail).toHaveTextContent("个人空间");
    expect(rail).toHaveTextContent("七年级数学");
    expect(tree).toHaveTextContent("教材与练习");
    expect(tree).toHaveTextContent("知识图谱");
    expect(tree).not.toHaveTextContent("个人空间");
  });

  it("uses ordinary pressed buttons for placeholder content views", () => {
    render(<WorkspaceShell />);

    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "知识图谱" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "教材原页" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("changes the selected workspace view and its center content", async () => {
    const user = userEvent.setup();
    render(<WorkspaceShell />);

    const graphButton = screen.getByRole("button", { name: "知识图谱" });
    const sourceButton = screen.getByRole("button", { name: "教材原页" });
    await user.click(sourceButton);

    expect(sourceButton).toHaveAttribute("aria-pressed", "true");
    expect(graphButton).toHaveAttribute("aria-pressed", "false");

    const workspace = screen.getByLabelText("知识工作区");
    expect(within(workspace).getByRole("heading", { name: "教材原页" })).toBeInTheDocument();
    expect(workspace).toHaveTextContent("查看教材原始页面及其版面内容。");
  });

  it("renders three keyboard-resizable content panes", async () => {
    const user = userEvent.setup();
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(400);
    render(<WorkspaceShell />);
    expect(screen.getByLabelText("当前空间内容")).toBeInTheDocument();
    expect(screen.getByLabelText("知识工作区")).toBeInTheDocument();
    expect(screen.getByLabelText("AI 家教")).toBeInTheDocument();

    const separators = screen.getAllByRole("separator");
    expect(separators).toHaveLength(2);

    const firstSeparator = separators[0];
    expect(firstSeparator).toHaveAttribute("tabindex", "0");
    expect(firstSeparator).toHaveAttribute("aria-valuemin");
    expect(firstSeparator).toHaveAttribute("aria-valuemax");
    expect(firstSeparator).toHaveAttribute("aria-valuenow");

    const initialValue = Number(firstSeparator.getAttribute("aria-valuenow"));
    firstSeparator.focus();
    await user.keyboard("{ArrowRight}");

    expect(Number(firstSeparator.getAttribute("aria-valuenow"))).toBeGreaterThan(initialValue);
  });

  it("keeps model and balance data available when knowledge loading fails", async () => {
    const user = userEvent.setup();
    mockApi.models.mockResolvedValue([
      {
        id: "study-model",
        display_name: "学习模型",
        provider: "example",
        price_summary: "按量计费",
      },
    ]);
    mockApi.billingMe.mockResolvedValue({ balance: "8.00", currency: "CNY", entries: [] });
    mockKnowledgeApi.list.mockRejectedValue(new Error("provider detail"));

    render(<WorkspaceShell />);
    await user.click(screen.getByRole("button", { name: "知识库" }));

    expect(await screen.findByText("知识库暂时无法加载。")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "学习模型" })).toBeInTheDocument();
    expect(screen.getByText("余额 ¥8.00")).toBeInTheDocument();
    expect(screen.getByLabelText("AI 家教")).toBeInTheDocument();
  });

  it("reloads the knowledge panel for the newly selected space", async () => {
    const user = userEvent.setup();
    mockKnowledgeApi.list.mockResolvedValue([]);
    render(
      <WorkspaceShell
        spaces={[
          { id: "personal", kind: "personal", name: "我的空间" },
          { id: "math", kind: "classroom", name: "七年级数学" },
        ]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "知识库" }));
    expect(await screen.findByText("当前空间还没有知识库。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "七年级数学" }));

    expect(mockKnowledgeApi.list).toHaveBeenLastCalledWith("math", expect.any(AbortSignal));
    expect(screen.getByLabelText("知识库面板")).toHaveTextContent("七年级数学");
  });
});
