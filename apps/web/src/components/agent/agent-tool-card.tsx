"use client";

import type { AgentToolView } from "@/lib/agent-events";

import styles from "./agent-tools.module.css";

export interface AgentToolCardProps {
  tool: AgentToolView;
  onOpenParent?: (toolCallId: string) => void;
}

type UnknownRecord = Record<string, unknown>;

const STATE_LABELS: Record<AgentToolView["state"], string> = {
  running: "运行中",
  completed: "已完成",
  failed: "失败",
};

function record(value: unknown): UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as UnknownRecord
    : {};
}

function firstString(...values: unknown[]): string | undefined {
  return values.find((value): value is string => typeof value === "string" && value.length > 0);
}

function firstNumber(...values: unknown[]): number | undefined {
  return values.find((value): value is number => typeof value === "number" && Number.isFinite(value));
}

function displayValue(value: unknown): string | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function duration(tool: AgentToolView): string | undefined {
  if (!tool.startedAt || !tool.completedAt) return undefined;
  const milliseconds = Date.parse(tool.completedAt) - Date.parse(tool.startedAt);
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return undefined;
  if (milliseconds < 1_000) return `${milliseconds} 毫秒`;
  const seconds = milliseconds / 1_000;
  return `${Number.isInteger(seconds) ? seconds : seconds.toFixed(2)} 秒`;
}

function canonicalKind(kind: string): string {
  return kind.trim().toLowerCase().replaceAll("-", "_");
}

function labelFor(kind: string, name: string): string {
  const labels: Record<string, string> = {
    bash: "命令",
    read: "读取文件",
    write: "写入文件",
    edit: "编辑文件",
    move: "移动文件",
    delete: "删除文件",
    web_search: "网页搜索",
    web_fetch: "网页读取",
    mcp: "MCP 工具",
    skill: "Skill",
    subagent: "Subagent",
  };
  return labels[kind] ?? name;
}

function Detail({ label, value, code = false }: { label: string; value?: string; code?: boolean }) {
  if (!value) return null;
  return (
    <div className={styles.detailRow}>
      <dt>{label}</dt>
      <dd>{code ? <code>{value}</code> : value}</dd>
    </div>
  );
}

function toolDetails(tool: AgentToolView, kind: string) {
  const input = record(tool.input);
  const payload = record(tool.payload);
  const output = record(tool.output);
  const path = firstString(input.path, input.file_path, payload.path, payload.file_path);
  const source = firstString(input.source, input.from, input.old_path, payload.source);
  const destination = firstString(
    input.destination,
    input.to,
    input.new_path,
    payload.destination,
  );
  const parentId = firstString(
    input.parent_tool_call_id,
    payload.parent_tool_call_id,
    input.parent_id,
    payload.parent_id,
  );
  const diff = firstString(payload.diff, input.diff, output.diff);

  if (kind === "bash") {
    return {
      primary: firstString(input.command, payload.command),
      rows: [
        ["工作目录", firstString(input.cwd, payload.cwd), true] as const,
        [
          "退出状态",
          firstNumber(output.exit_code, output.exitCode, payload.exit_code, payload.exitCode) === undefined
            ? undefined
            : `退出码 ${firstNumber(output.exit_code, output.exitCode, payload.exit_code, payload.exitCode)}`,
          false,
        ] as const,
      ],
      parentId,
      diff,
    };
  }

  if (["write", "edit", "delete", "read"].includes(kind)) {
    return { primary: path, rows: [], parentId, diff };
  }
  if (kind === "move") {
    return {
      primary: source && destination ? `${source} → ${destination}` : source ?? destination,
      rows: [],
      parentId,
      diff,
    };
  }
  if (kind === "web_search") {
    return { primary: firstString(input.query, payload.query), rows: [], parentId, diff };
  }
  if (kind === "web_fetch") {
    return { primary: firstString(input.url, payload.url), rows: [], parentId, diff };
  }
  if (kind === "mcp") {
    const server = firstString(input.server, input.server_name, payload.server);
    const mcpTool = firstString(input.tool, input.tool_name, payload.tool);
    return {
      primary: server && mcpTool ? `${server} / ${mcpTool}` : server ?? mcpTool,
      rows: [],
      parentId,
      diff,
    };
  }
  if (kind === "skill") {
    const skill = firstString(input.skill, input.name, payload.skill, payload.name, tool.name);
    return { primary: skill ? `Skill: ${skill}` : undefined, rows: [], parentId, diff };
  }
  if (kind === "subagent") {
    const name = firstString(input.name, input.agent, payload.name, tool.name);
    const subagentId = firstString(payload.subagent_id, input.subagent_id);
    return {
      primary: name ? `Subagent: ${name}` : undefined,
      rows: subagentId ? [["子智能体 ID", subagentId, true] as const] : [],
      parentId,
      diff,
    };
  }
  return { primary: displayValue(tool.input), rows: [], parentId, diff };
}

export function AgentToolCard({ tool, onOpenParent }: AgentToolCardProps) {
  const kind = canonicalKind(tool.kind || tool.name);
  const details = toolDetails(tool, kind);
  const elapsed = duration(tool);
  const outputRecord = record(tool.output);
  const output = kind === "bash"
    ? firstString(outputRecord.stdout, outputRecord.stderr) ?? displayValue(tool.output)
    : displayValue(tool.output);

  return (
    <article
      className={`${styles.toolCard} ${styles[`state_${tool.state}`]}`}
      data-testid={`agent-tool-${kind}`}
    >
      <header className={styles.toolHeader}>
        <div>
          <span className={styles.toolKind}>{labelFor(kind, tool.name)}</span>
          <strong>{tool.name}</strong>
        </div>
        <div className={styles.statusGroup}>
          {elapsed ? <span>{elapsed}</span> : null}
          <span className={styles.status}>{STATE_LABELS[tool.state]}</span>
        </div>
      </header>

      {details.primary ? <pre className={styles.primary}>{details.primary}</pre> : null}

      {details.rows.length > 0 ? (
        <dl className={styles.details}>
          {details.rows.map(([label, value, code]) => (
            <Detail code={code} key={label} label={label} value={value} />
          ))}
        </dl>
      ) : null}

      {details.parentId ? (
        <button
          className={styles.parentLink}
          onClick={() => onOpenParent?.(details.parentId as string)}
          type="button"
        >
          打开父工具 {details.parentId}
        </button>
      ) : null}

      {details.diff ? (
        <section className={styles.section}>
          <h4>Diff</h4>
          <pre className={styles.diff}>{details.diff}</pre>
        </section>
      ) : null}

      {tool.progress ? (
        <section aria-live="polite" className={styles.section}>
          <h4>实时输出</h4>
          <pre className={styles.output}>{tool.progress}</pre>
        </section>
      ) : null}

      {output ? (
        <section className={styles.section}>
          <h4>输出</h4>
          <pre className={styles.output}>{output}</pre>
        </section>
      ) : null}

      {tool.error ? <p className={styles.error} role="alert">{tool.error}</p> : null}

      {tool.sidecar ? (
        <footer className={styles.sidecarMeta}>
          Sidecar · {tool.sidecar.mediaType} · {tool.sidecar.size} bytes
        </footer>
      ) : null}
    </article>
  );
}
