import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AgentEventEnvelope, AgentView } from "@/lib/agent-events";
import { emptyAgentView } from "@/lib/agent-events";

import { AgentMessageList } from "./agent-message-list";

function event(
  eventId: string,
  sequence: number,
  eventType: AgentEventEnvelope["event_type"],
  turnId: string | null,
  payload: Record<string, unknown>,
): AgentEventEnvelope {
  return {
    event_id: eventId,
    session_id: "session-1",
    turn_id: turnId,
    sequence,
    event_type: eventType,
    timestamp: `2026-08-29T00:00:0${sequence}Z`,
    payload,
    idempotency_key: eventId,
  };
}

function view(overrides: Partial<AgentView>): AgentView {
  return { ...emptyAgentView(), ...overrides };
}

describe("AgentMessageList", () => {
  it("renders user and streaming assistant messages grouped by turn", () => {
    render(
      <AgentMessageList
        view={view({
          messages: [
            {
              id: "message-user-1",
              eventId: "event-user-1",
              turnId: "turn-1",
              role: "user",
              text: "比较两个章节",
              streaming: false,
            },
            {
              id: "message-assistant-1",
              eventId: "event-assistant-1",
              turnId: "turn-1",
              role: "assistant",
              text: "正在综合完整材料",
              streaming: true,
            },
          ],
        })}
      />,
    );

    const turn = screen.getByTestId("turn-turn-1");
    expect(within(turn).getByText("比较两个章节")).toBeInTheDocument();
    const assistant = within(turn).getByTestId("message-message-assistant-1");
    expect(assistant).toHaveTextContent("正在综合完整材料");
    expect(assistant).toHaveAttribute("aria-busy", "true");
  });

  it("renders thinking as a collapsible block", () => {
    render(
      <AgentMessageList
        view={view({
          thinking: [
            {
              id: "thinking-1",
              eventId: "event-thinking-1",
              turnId: "turn-1",
              text: "逐项检查来源并规划下一步",
              streaming: true,
            },
          ],
        })}
      />,
    );

    const details = screen.getByTestId("thinking-thinking-1");
    expect(details.tagName).toBe("DETAILS");
    expect(within(details).getByText("思考中")).toBeInTheDocument();
    expect(within(details).getByText("逐项检查来源并规划下一步")).toBeInTheDocument();
  });

  it("opens Vault citations with exact provenance and renders only safe web links", async () => {
    const user = userEvent.setup();
    const onOpenVaultCitation = vi.fn();
    const citationEvent = event("event-citations", 1, "model_text_delta", "turn-1", {
      citations: [
        {
          id: "citation-vault-1",
          kind: "vault",
          label: "第一章定义",
          knowledge_base_id: "kb-1",
          vault_file_id: "vault-file-1",
          path: "课程/第一章.md",
          heading: "定义",
        },
        {
          id: "citation-web-1",
          kind: "web",
          label: "官方文档",
          url: "https://example.com/full-source",
        },
        {
          id: "citation-web-danger",
          kind: "web",
          label: "危险链接",
          url: "javascript:alert(1)",
        },
      ],
    });

    render(
      <AgentMessageList
        onOpenVaultCitation={onOpenVaultCitation}
        view={view({ events: [citationEvent], lastSequence: 1 })}
      />,
    );

    await user.click(screen.getByRole("button", { name: "第一章定义" }));
    expect(onOpenVaultCitation).toHaveBeenCalledWith({
      knowledgeBaseId: "kb-1",
      vaultFileId: "vault-file-1",
      path: "课程/第一章.md",
      heading: "定义",
    });

    const webLink = screen.getByRole("link", { name: "官方文档" });
    expect(webLink).toHaveAttribute("href", "https://example.com/full-source");
    expect(webLink).toHaveAttribute("target", "_blank");
    expect(webLink).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(webLink).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
    expect(screen.queryByRole("link", { name: "危险链接" })).not.toBeInTheDocument();
    expect(screen.getByText("危险链接")).toBeInTheDocument();
  });

  it("never exposes a Vault path as the citation label when provenance lacks a safe label", () => {
    const secretPath = "机密/未加入空间.md";
    render(
      <AgentMessageList
        view={view({
          events: [event("event-secret-citation", 1, "model_text_delta", "turn-1", {
            citations: [{
              id: "citation-secret",
              kind: "vault",
              knowledge_base_id: "kb-foreign",
              vault_file_id: "file-foreign",
              path: secretPath,
              space_id: "space-foreign",
            }],
          })],
          lastSequence: 1,
        })}
      />,
    );

    expect(screen.queryByText(secretPath)).not.toBeInTheDocument();
  });
  it("hides unjoined Vault citations and redacts unreadable joined-space metadata", async () => {
    const user = userEvent.setup();
    const onOpenVaultCitation = vi.fn();
    render(
      <AgentMessageList
        onOpenVaultCitation={onOpenVaultCitation}
        vaultCitationAccess={{
          joinedSpaceIds: ["space-current", "space-joined"],
          readableVaultScopes: [{ spaceId: "space-current", knowledgeBaseId: "kb-current" }],
        }}
        view={view({
          events: [event("event-protected-citations", 1, "model_text_delta", "turn-1", {
            citations: [
              {
                id: "citation-foreign",
                kind: "vault",
                label: "外部机密标题",
                excerpt: "外部机密摘录",
                knowledge_base_id: "kb-foreign",
                vault_file_id: "file-foreign",
                path: "机密/外部.md",
                space_id: "space-foreign",
              },
              {
                id: "citation-unreadable",
                kind: "vault",
                label: "未授权机密标题",
                excerpt: "未授权机密摘录",
                knowledge_base_id: "kb-unreadable",
                vault_file_id: "file-unreadable",
                path: "机密/未授权.md",
                space_id: "space-joined",
              },
            ],
          })],
          lastSequence: 1,
        })}
      />,
    );

    expect(screen.queryByText(/外部机密|未授权机密|机密\//)).not.toBeInTheDocument();
    const protectedCitation = screen.getByText("受保护的 Vault 引用");
    expect(protectedCitation.tagName).not.toBe("BUTTON");
    await user.click(protectedCitation);
    expect(onOpenVaultCitation).not.toHaveBeenCalled();
  });
  it("binds readability to the exact space and knowledge-base pair", () => {
    const secretLabel = "另一空间的机密标题";
    const secretExcerpt = "另一空间的机密摘要";
    const secretPath = "机密/跨空间错配.md";
    const mismatchedPair = event("event-pair-mismatch", 1, "model_text_delta", "turn-1", {
      citations: [{
        id: "citation-pair-mismatch",
        kind: "vault",
        label: secretLabel,
        excerpt: secretExcerpt,
        knowledge_base_id: "kb-personal-readable",
        path: secretPath,
        space_id: "space-class-joined",
        vault_file_id: "file-pair-mismatch",
      }],
    });

    render(
      <AgentMessageList
        vaultCitationAccess={{
          joinedSpaceIds: ["space-personal", "space-class-joined"],
          readableVaultScopes: [{
            spaceId: "space-personal",
            knowledgeBaseId: "kb-personal-readable",
          }],
        }}
        view={view({ events: [mismatchedPair], lastSequence: 1 })}
      />,
    );

    expect(screen.getByText("受保护的 Vault 引用").tagName).not.toBe("BUTTON");
    expect(screen.queryByText(secretLabel)).not.toBeInTheDocument();
    expect(screen.queryByText(secretExcerpt)).not.toBeInTheDocument();
    expect(screen.queryByText(secretPath)).not.toBeInTheDocument();
  });

  it("does not authorize or expose a Vault citation that omits space_id", async () => {
    const user = userEvent.setup();
    const onOpenVaultCitation = vi.fn();
    const secrets = ["缺失空间机密标题", "缺失空间机密章节", "缺失空间机密摘要", "机密/缺失空间.md", "file-missing-space"];

    render(
      <AgentMessageList
        onOpenVaultCitation={onOpenVaultCitation}
        vaultCitationAccess={{
          joinedSpaceIds: ["space-current"],
          readableVaultScopes: [{ spaceId: "space-current", knowledgeBaseId: "kb-current" }],
        }}
        view={view({
          events: [event("event-missing-space", 1, "model_text_delta", "turn-1", {
            citations: [{
              id: "citation-missing-space",
              kind: "vault",
              label: secrets[0],
              heading: secrets[1],
              excerpt: secrets[2],
              path: secrets[3],
              vault_file_id: secrets[4],
              knowledge_base_id: "kb-current",
            }],
          })],
          lastSequence: 1,
        })}
      />,
    );

    const protectedCitation = screen.getByText("受保护的 Vault 引用");
    expect(protectedCitation.tagName).not.toBe("BUTTON");
    for (const secret of secrets) expect(document.body).not.toHaveTextContent(secret);
    await user.click(protectedCitation);
    expect(onOpenVaultCitation).not.toHaveBeenCalled();
  });

  it("projects usage and compaction event payloads through strict safe fields", () => {
    const secrets = ["事件机密标题", "事件机密章节", "事件机密摘要", "机密/事件.md"];
    const sensitiveCitation = {
      kind: "vault",
      space_id: "space-foreign",
      knowledge_base_id: "kb-foreign",
      vault_file_id: "file-foreign",
      label: secrets[0],
      heading: secrets[1],
      excerpt: secrets[2],
      path: secrets[3],
    };
    const events = [
      event("event-compaction-safe", 1, "compaction", "turn-1", {
        summary: "已安全压缩",
        retained_tokens: 18000,
        citations: [sensitiveCitation],
      }),
      event("event-usage-safe", 2, "usage", "turn-1", {
        input_tokens: 1200,
        output_tokens: 340,
        sources: [sensitiveCitation],
      }),
    ];

    render(
      <AgentMessageList
        vaultCitationAccess={{
          joinedSpaceIds: ["space-current"],
          readableVaultScopes: [{ spaceId: "space-current", knowledgeBaseId: "kb-current" }],
        }}
        view={view({ events, lastSequence: 2 })}
      />,
    );

    expect(screen.getByTestId("compaction-event-compaction-safe")).toHaveTextContent("已安全压缩");
    expect(screen.getByTestId("usage-event-usage-safe")).toHaveTextContent("1200");
    for (const secret of secrets) expect(document.body).not.toHaveTextContent(secret);
  });

  it("ignores citations embedded in usage, compaction, and unknown event payloads", async () => {
    const user = userEvent.setup();
    const onOpenVaultCitation = vi.fn();
    const vaultCitation = (id: string, label: string) => ({
      id,
      kind: "vault",
      space_id: "space-current",
      knowledge_base_id: "kb-current",
      vault_file_id: `file-${id}`,
      label,
      heading: `${label}-heading`,
      excerpt: `${label}-excerpt`,
      path: `机密/${label}.md`,
    });
    const webCitation = (id: string, label: string) => ({
      id,
      kind: "web",
      label,
      excerpt: `${label}-excerpt`,
      url: `https://example.com/${id}`,
    });
    const vaultLabels = [
      "usage-citations-vault-secret",
      "usage-citation-vault-secret",
      "compaction-citations-vault-secret",
      "compaction-sources-vault-secret",
      "unknown-event-vault-secret",
    ];
    const webLabels = [
      "usage-sources-web-secret",
      "compaction-citation-web-secret",
      "compaction-sources-web-secret",
    ];
    const events = [
      event("event-usage-citations", 1, "usage", "turn-1", {
        input_tokens: 1,
        citations: [vaultCitation("usage-citations", vaultLabels[0])],
      }),
      event("event-usage-citation", 2, "usage", "turn-1", {
        input_tokens: 2,
        citation: vaultCitation("usage-citation", vaultLabels[1]),
      }),
      event("event-usage-sources", 3, "usage", "turn-1", {
        input_tokens: 3,
        sources: [webCitation("usage-sources", webLabels[0])],
      }),
      event("event-compaction-citations", 4, "compaction", "turn-1", {
        summary: "safe-compaction-citations",
        citations: [vaultCitation("compaction-citations", vaultLabels[2])],
      }),
      event("event-compaction-citation", 5, "compaction", "turn-1", {
        summary: "safe-compaction-citation",
        citation: webCitation("compaction-citation", webLabels[1]),
      }),
      event("event-compaction-sources", 6, "compaction", "turn-1", {
        summary: "safe-compaction-sources",
        sources: [
          vaultCitation("compaction-sources", vaultLabels[3]),
          webCitation("compaction-sources-web", webLabels[2]),
        ],
      }),
      event(
        "event-future-unknown",
        7,
        "future_citation_event" as AgentEventEnvelope["event_type"],
        "turn-1",
        { citations: [vaultCitation("unknown-event", vaultLabels[4])] },
      ),
    ];

    render(
      <AgentMessageList
        onOpenVaultCitation={onOpenVaultCitation}
        vaultCitationAccess={{
          joinedSpaceIds: ["space-current"],
          readableVaultScopes: [{ spaceId: "space-current", knowledgeBaseId: "kb-current" }],
        }}
        view={view({ events, lastSequence: 7 })}
      />,
    );

    for (const label of vaultLabels) {
      const leakedButton = screen.queryByRole("button", { name: label });
      if (leakedButton) await user.click(leakedButton);
    }
    expect(onOpenVaultCitation).not.toHaveBeenCalled();

    for (const label of [...vaultLabels, ...webLabels]) {
      expect(document.body).not.toHaveTextContent(label);
      expect(document.body).not.toHaveTextContent(`${label}-heading`);
      expect(document.body).not.toHaveTextContent(`${label}-excerpt`);
    }
    for (const label of vaultLabels) {
      expect(document.body).not.toHaveTextContent(`机密/${label}.md`);
    }
  });

  it("projects reducer-derived usage and compaction payloads through the same safe fields", () => {
    const secrets = ["派生机密标题", "派生机密章节", "派生机密摘要", "机密/派生.md"];
    const sensitiveSource = {
      kind: "vault",
      knowledge_base_id: "kb-current",
      vault_file_id: "file-missing-space",
      label: secrets[0],
      heading: secrets[1],
      excerpt: secrets[2],
      path: secrets[3],
    };

    render(
      <AgentMessageList
        view={view({
          compactions: [{ summary: "派生压缩安全摘要", retained_tokens: 9000, sources: [sensitiveSource] }],
          usage: { input_tokens: 42, output_tokens: 7, citations: [sensitiveSource] },
        })}
      />,
    );

    expect(screen.getByTestId("compaction-view-0")).toHaveTextContent("派生压缩安全摘要");
    expect(screen.getByTestId("usage-view")).toHaveTextContent("42");
    for (const secret of secrets) expect(document.body).not.toHaveTextContent(secret);
  });

  it("renders compaction, usage and error events without hiding source payloads", () => {
    const events = [
      event("event-compaction", 1, "compaction", "turn-1", {
        summary: "已压缩较早对话，但原事件仍可重放",
        retained_tokens: 18000,
      }),
      event("event-usage", 2, "usage", "turn-1", {
        input_tokens: 1200,
        output_tokens: 340,
      }),
      event("event-error", 3, "error", "turn-1", {
        code: "WEB_FETCH_FAILED",
        message: "网页读取失败，可继续重试",
      }),
    ];

    render(
      <AgentMessageList
        view={view({
          compactions: [events[0].payload],
          error: { code: "WEB_FETCH_FAILED", message: "网页读取失败，可继续重试" },
          events,
          lastSequence: 3,
          usage: events[1].payload,
        })}
      />,
    );

    expect(screen.getByTestId("compaction-event-compaction")).toHaveTextContent(
      "已压缩较早对话，但原事件仍可重放",
    );
    expect(screen.getByTestId("usage-event-usage")).toHaveTextContent("input tokens");
    expect(screen.getByTestId("usage-event-usage")).toHaveTextContent("1200");
    expect(screen.getByRole("alert")).toHaveTextContent("WEB_FETCH_FAILED");
    expect(screen.getByRole("alert")).toHaveTextContent("网页读取失败，可继续重试");
  });

  it("keeps stable message nodes while replayed history is rerendered and appended", () => {
    const firstView = view({
      messages: [
        {
          id: "message-assistant-stable",
          eventId: "event-assistant-stable",
          turnId: "turn-stable",
          role: "assistant",
          text: "已保存的历史回答",
          streaming: false,
        },
      ],
    });
    const { rerender } = render(<AgentMessageList view={firstView} />);
    const originalNode = screen.getByTestId("message-message-assistant-stable");

    rerender(
      <AgentMessageList
        view={{
          ...firstView,
          messages: [
            ...firstView.messages,
            {
              id: "message-user-new",
              eventId: "event-user-new",
              turnId: "turn-new",
              role: "user",
              text: "下一轮",
              streaming: false,
            },
          ],
        }}
      />,
    );

    expect(screen.getByTestId("message-message-assistant-stable")).toBe(originalNode);
  });

  it("renders legacy messages that do not have a turn id", () => {
    render(
      <AgentMessageList
        view={view({
          messages: [
            {
              id: "legacy-message",
              eventId: "legacy-event",
              turnId: null,
              role: "assistant",
              text: "旧会话消息",
              streaming: false,
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("旧会话消息")).toBeInTheDocument();
  });
});
