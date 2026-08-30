"use client";

import type { AgentDiagnostics as AgentDiagnosticsValue } from "@/lib/agent-api";

import styles from "./agent-settings.module.css";

export interface AgentDiagnosticsProps {
  value: AgentDiagnosticsValue;
}

type DiagnosticRecord = Record<string, unknown>;

function asRecord(value: unknown): DiagnosticRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as DiagnosticRecord
    : null;
}

const SAFE_STATUSES = new Set([
  "healthy",
  "ready",
  "ok",
  "connected",
  "running",
  "warm",
  "degraded",
  "unavailable",
  "unhealthy",
  "failed",
  "error",
  "disconnected",
  "unknown",
]);

function statusOf(value: unknown): string {
  const record = asRecord(value);
  if (!record) return "unknown";
  for (const key of ["status", "state", "health"] as const) {
    const raw = record[key];
    if (typeof raw !== "string") continue;
    const candidate = raw.toLowerCase();
    return SAFE_STATUSES.has(candidate) ? candidate : "unknown";
  }
  if (typeof record.healthy === "boolean") return record.healthy ? "healthy" : "degraded";
  return "unknown";
}

function labelOf(value: unknown, fallback: string): string {
  const record = asRecord(value);
  if (!record) return fallback;
  for (const key of ["name", "id", "provider", "server"] as const) {
    const raw = record[key];
    if (typeof raw === "string" && raw) return raw;
  }
  return fallback;
}

function safeTestId(value: string): string {
  const normalized = value.toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
  return normalized.replace(/^-+|-+$/g, "") || "unknown";
}

function DiagnosticRow({
  kind,
  label,
  status,
}: {
  kind: "runtime" | "provider" | "mcp";
  label: string;
  status: string;
}) {
  const degraded = !["healthy", "ready", "ok", "connected"].includes(status);
  return (
    <li
      className={degraded ? styles.diagnosticDegraded : styles.diagnosticHealthy}
      data-testid={kind === "runtime" ? "diagnostic-runtime" : `diagnostic-${kind}-${safeTestId(label)}`}
    >
      <span>{label}</span>
      <strong>{status}</strong>
    </li>
  );
}

export function AgentDiagnostics({ value }: AgentDiagnosticsProps) {
  const providers = Array.isArray(value.providers) ? value.providers : [];
  const mcp = Array.isArray(value.mcp) ? value.mcp : [];

  return (
    <section aria-labelledby="agent-diagnostics-heading" className={styles.diagnostics}>
      <h2 id="agent-diagnostics-heading">Diagnostics</h2>

      <div className={styles.diagnosticSection}>
        <h3>Runtime</h3>
        <ul>
          <DiagnosticRow kind="runtime" label="Runtime" status={statusOf(value.runtime)} />
        </ul>
      </div>

      <div className={styles.diagnosticSection}>
        <h3>Providers</h3>
        {providers.length > 0 ? (
          <ul>
            {providers.map((provider, index) => {
              const label = labelOf(provider, `Provider ${index + 1}`);
              return (
                <DiagnosticRow
                  key={`${label}-${index}`}
                  kind="provider"
                  label={label}
                  status={statusOf(provider)}
                />
              );
            })}
          </ul>
        ) : <p>No provider diagnostics</p>}
      </div>

      <div className={styles.diagnosticSection}>
        <h3>MCP</h3>
        {mcp.length > 0 ? (
          <ul>
            {mcp.map((server, index) => {
              const label = labelOf(server, `MCP ${index + 1}`);
              return (
                <DiagnosticRow
                  key={`${label}-${index}`}
                  kind="mcp"
                  label={label}
                  status={statusOf(server)}
                />
              );
            })}
          </ul>
        ) : <p>No MCP diagnostics</p>}
      </div>
    </section>
  );
}
