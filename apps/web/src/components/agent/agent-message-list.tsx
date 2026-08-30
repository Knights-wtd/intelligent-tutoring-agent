import type {
  AgentEventEnvelope,
  AgentMessageBlock,
  AgentThinkingBlock,
  AgentView,
} from "@/lib/agent-events";

import styles from "./agent-conversation.module.css";

export interface VaultCitationTarget {
  knowledgeBaseId: string;
  vaultFileId: string;
  path: string;
  heading?: string;
  spaceId?: string;
}

export interface ReadableVaultScope {
  spaceId: string;
  knowledgeBaseId: string;
}

export interface VaultCitationAccessScope {
  joinedSpaceIds: readonly string[];
  readableVaultScopes: readonly ReadableVaultScope[];
}

export interface AgentMessageListProps {
  view: AgentView;
  onOpenVaultCitation?: (citation: VaultCitationTarget) => void;
  vaultCitationAccess?: VaultCitationAccessScope;
}

interface CitationView {
  id: string;
  turnId: string | null;
  kind: "vault" | "web";
  label: string;
  excerpt?: string;
  vault?: VaultCitationTarget;
  url?: string;
}

interface TurnView {
  id: string;
  messages: AgentMessageBlock[];
  thinking: AgentThinkingBlock[];
  citations: CitationView[];
  events: AgentEventEnvelope[];
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function safeWebUrl(value: unknown): string | undefined {
  const candidate = text(value);
  if (!candidate) return undefined;
  try {
    const parsed = new URL(candidate);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}

const citationBearingEventTypes: ReadonlySet<AgentEventEnvelope["event_type"]> = new Set([
  "model_text_delta",
]);

function citationPayloads(event: AgentEventEnvelope): unknown[] {
  if (!citationBearingEventTypes.has(event.event_type)) return [];
  const citations = event.payload.citations;
  if (Array.isArray(citations)) return citations;
  const sources = event.payload.sources;
  if (Array.isArray(sources)) return sources;
  return event.payload.citation === undefined ? [] : [event.payload.citation];
}

function parseCitations(
  events: AgentEventEnvelope[],
  access?: VaultCitationAccessScope,
): CitationView[] {
  const citations: CitationView[] = [];
  const joinedSpaceIds = access ? new Set(access.joinedSpaceIds) : null;
  const readableVaultScopes = access
    ? new Set(access.readableVaultScopes.map(({ spaceId, knowledgeBaseId }) => `${spaceId}\0${knowledgeBaseId}`))
    : null;

  for (const event of events) {
    citationPayloads(event).forEach((rawCitation, index) => {
      const citation = record(rawCitation);
      if (!citation) return;
      const kind = text(citation.kind) ?? text(citation.type);
      const id = text(citation.id) ?? `${event.event_id}:citation:${index}`;
      const explicitLabel = text(citation.label) ?? text(citation.title) ?? text(citation.heading);
      const excerpt = text(citation.excerpt) ?? text(citation.content);

      if (kind === "vault") {
        const knowledgeBaseId = text(citation.knowledge_base_id) ?? text(citation.knowledgeBaseId);
        if (!knowledgeBaseId) return;
        const spaceId = text(citation.space_id) ?? text(citation.spaceId);

        if (access) {
          if (!spaceId) {
            citations.push({
              id,
              turnId: event.turn_id,
              kind: "vault",
              label: "受保护的 Vault 引用",
            });
            return;
          }
          if (!joinedSpaceIds?.has(spaceId)) return;
          if (!readableVaultScopes?.has(`${spaceId}\0${knowledgeBaseId}`)) {
            citations.push({
              id,
              turnId: event.turn_id,
              kind: "vault",
              label: "受保护的 Vault 引用",
            });
            return;
          }
        }

        const vaultFileId = text(citation.vault_file_id) ?? text(citation.vaultFileId);
        const path = text(citation.path);
        if (!vaultFileId || !path) return;
        const heading = text(citation.heading);
        citations.push({
          id,
          turnId: event.turn_id,
          kind: "vault",
          label: explicitLabel ?? "Vault 引用",
          ...(excerpt ? { excerpt } : {}),
          vault: {
            knowledgeBaseId,
            vaultFileId,
            path,
            ...(heading ? { heading } : {}),
            ...(spaceId ? { spaceId } : {}),
          },
        });
        return;
      }

      if (kind === "web") {
        const label = explicitLabel ?? "来源";
        citations.push({
          id,
          turnId: event.turn_id,
          kind: "web",
          label,
          ...(excerpt ? { excerpt } : {}),
          ...(safeWebUrl(citation.url) ? { url: safeWebUrl(citation.url) } : {}),
        });
      }
    });
  }
  return citations;
}
const usageFields = [
  "provider",
  "model",
  "input_tokens",
  "output_tokens",
  "cache_read_tokens",
  "cache_write_tokens",
  "compaction_count",
  "tool_call_count",
  "web_request_count",
  "file_read_bytes",
  "command_duration_ms",
  "sidecar_bytes",
  "session_duration_ms",
  "duration_ms",
  "cost",
  "cost_usd",
] as const;

const compactionFields = [
  "summary",
  "subtype",
  "reason",
  "before_tokens",
  "after_tokens",
  "retained_tokens",
  "compacted_tokens",
  "context_window",
  "compaction_count",
] as const;

type SafeMetaValue = string | number | boolean | null;

function safeMetaPayload(
  payload: Record<string, unknown>,
  fields: readonly string[],
): Record<string, SafeMetaValue> {
  const safe: Record<string, SafeMetaValue> = {};
  for (const field of fields) {
    const value = payload[field];
    if (
      value === null
      || typeof value === "string"
      || typeof value === "number"
      || typeof value === "boolean"
    ) {
      safe[field] = value;
    }
  }
  return safe;
}

function displayName(key: string): string {
  return key.replaceAll("_", " ");
}

function MetaPayload({ payload }: { payload: Record<string, SafeMetaValue> }) {
  return (
    <dl className={styles.metaGrid}>
      {Object.entries(payload).map(([key, value]) => (
        <div key={key}>
          <dt>{displayName(key)}</dt>
          <dd>{value === null ? "null" : String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function CitationList({
  citations,
  onOpenVaultCitation,
}: {
  citations: CitationView[];
  onOpenVaultCitation?: (citation: VaultCitationTarget) => void;
}) {
  if (citations.length === 0) return null;
  return (
    <section className={styles.citations} aria-label="引用来源">
      <h4>来源</h4>
      <ul>
        {citations.map((citation) => (
          <li key={citation.id}>
            {citation.kind === "vault" && citation.vault ? (
              <button
                className={styles.citationButton}
                onClick={() => onOpenVaultCitation?.(citation.vault!)}
                type="button"
              >
                {citation.label}
              </button>
            ) : citation.url ? (
              <a href={citation.url} rel="noopener noreferrer" target="_blank">
                {citation.label}
              </a>
            ) : (
              <span>{citation.label}</span>
            )}
            {citation.excerpt && <p>{citation.excerpt}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Compaction({ event }: { event: AgentEventEnvelope }) {
  return (
    <aside className={styles.compaction} data-testid={`compaction-${event.event_id}`}>
      <strong>上下文压缩</strong>
      <MetaPayload payload={safeMetaPayload(event.payload, compactionFields)} />
    </aside>
  );
}

function Usage({ event }: { event: AgentEventEnvelope }) {
  return (
    <aside className={styles.usage} data-testid={`usage-${event.event_id}`}>
      <strong>用量</strong>
      <MetaPayload payload={safeMetaPayload(event.payload, usageFields)} />
    </aside>
  );
}

function Turn({
  turn,
  onOpenVaultCitation,
}: {
  turn: TurnView;
  onOpenVaultCitation?: (citation: VaultCitationTarget) => void;
}) {
  return (
    <section className={styles.turn} data-testid={`turn-${turn.id}`}>
      {turn.messages.map((message) => (
        <article
          aria-busy={message.streaming}
          className={`${styles.message} ${message.role === "user" ? styles.userMessage : styles.assistantMessage} ${message.streaming ? styles.streaming : ""}`}
          data-testid={`message-${message.id}`}
          key={message.id}
        >
          <span className={styles.messageRole}>{message.role === "user" ? "你" : "Agent"}</span>
          <p>{message.text}</p>
        </article>
      ))}
      {turn.thinking.map((block) => (
        <details
          className={styles.thinking}
          data-testid={`thinking-${block.id}`}
          key={block.id}
        >
          <summary>{block.streaming ? "思考中" : "思考过程"}</summary>
          <p>{block.text}</p>
        </details>
      ))}
      <CitationList
        citations={turn.citations}
        onOpenVaultCitation={onOpenVaultCitation}
      />
      {turn.events.map((event) => {
        if (event.event_type === "compaction") return <Compaction event={event} key={event.event_id} />;
        if (event.event_type === "usage") return <Usage event={event} key={event.event_id} />;
        return null;
      })}
    </section>
  );
}

function buildTurns(view: AgentView, citations: CitationView[]): TurnView[] {
  const orderedIds: string[] = [];
  const seen = new Set<string>();
  const add = (id: string) => {
    if (seen.has(id)) return;
    seen.add(id);
    orderedIds.push(id);
  };

  for (const event of view.events) {
    if (event.turn_id) add(event.turn_id);
  }
  for (const message of view.messages) {
    if (message.turnId) add(message.turnId);
  }
  for (const block of view.thinking) {
    if (block.turnId) add(block.turnId);
  }

  const turns = orderedIds.map((id) => ({
    id,
    messages: view.messages.filter((message) => message.turnId === id),
    thinking: view.thinking.filter((block) => block.turnId === id),
    citations: citations.filter((citation) => citation.turnId === id),
    events: view.events.filter(
      (event) => event.turn_id === id && ["compaction", "usage"].includes(event.event_type),
    ),
  }));

  for (const message of view.messages.filter((item) => item.turnId === null)) {
    turns.push({
      id: `legacy-${message.id}`,
      messages: [message],
      thinking: [],
      citations: [],
      events: [],
    });
  }
  for (const block of view.thinking.filter((item) => item.turnId === null)) {
    turns.push({
      id: `legacy-${block.id}`,
      messages: [],
      thinking: [block],
      citations: [],
      events: [],
    });
  }

  const unscopedCitations = citations.filter((citation) => citation.turnId === null);
  const unscopedEvents = view.events.filter(
    (event) => event.turn_id === null && ["compaction", "usage"].includes(event.event_type),
  );
  if (unscopedCitations.length > 0 || unscopedEvents.length > 0) {
    turns.push({
      id: "unscoped-events",
      messages: [],
      thinking: [],
      citations: unscopedCitations,
      events: unscopedEvents,
    });
  }

  return turns;
}

export function AgentMessageList({
  view,
  onOpenVaultCitation,
  vaultCitationAccess,
}: AgentMessageListProps) {
  const citations = parseCitations(view.events, vaultCitationAccess);
  const turns = buildTurns(view, citations);
  const rawCompactionEvents = view.events.filter((event) => event.event_type === "compaction");
  const rawCompactionIds = new Set(rawCompactionEvents.map((event) => event.event_id));
  const rawCompactionPayloads = new Set(
    rawCompactionEvents.map((event) => JSON.stringify(
      safeMetaPayload(event.payload, compactionFields),
    )),
  );
  const rawUsageEvents = view.events.filter((event) => event.event_type === "usage");

  return (
    <div className={styles.messageList} aria-label="Agent 对话">
      {turns.map((turn) => (
        <Turn
          key={turn.id}
          onOpenVaultCitation={onOpenVaultCitation}
          turn={turn}
        />
      ))}

      {view.compactions.map((payload, index) => {
        const eventId = text(payload.event_id);
        if (
          (eventId && rawCompactionIds.has(eventId))
          || rawCompactionPayloads.has(JSON.stringify(safeMetaPayload(payload, compactionFields)))
        ) return null;
        return (
          <aside
            className={styles.compaction}
            data-testid={`compaction-view-${eventId ?? index}`}
            key={eventId ?? `compaction:${index}`}
          >
            <strong>上下文压缩</strong>
            <MetaPayload payload={safeMetaPayload(payload, compactionFields)} />
          </aside>
        );
      })}

      {rawUsageEvents.length === 0 && Object.keys(view.usage).length > 0 && (
        <aside className={styles.usage} data-testid="usage-view">
          <strong>用量</strong>
          <MetaPayload payload={safeMetaPayload(view.usage, usageFields)} />
        </aside>
      )}

      {view.error && (
        <aside className={styles.error} role="alert">
          {view.error.code && <strong>{view.error.code}</strong>}
          <p>{view.error.message}</p>
        </aside>
      )}
    </div>
  );
}
