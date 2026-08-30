"use client";

import type { AgentDiagnostics as AgentDiagnosticsValue } from "@/lib/agent-api";

import { AgentDiagnostics } from "./agent-diagnostics";
import styles from "./agent-settings.module.css";

export const FARO_PROVIDER = "faro";
export const FARO_MODEL = "gemini-3.7-flash-tiered";
export const FARO_CONTEXT_WINDOW = 32_000;

export type AgentPermissionMode = "bypassPermissions" | "normal" | "plan";

export interface AgentSettingsValue {
  provider?: string;
  model?: string;
  context_window?: number;
  permission_mode?: AgentPermissionMode;
  workspace_roots?: string[];
  mcp_enabled?: boolean;
  skills_enabled?: boolean;
  subagents_enabled?: boolean;
  web_enabled?: boolean;
  [key: string]: unknown;
}

export interface AgentProviderCapability {
  contextWindow: number;
  secretConfigured: boolean;
}

export interface AgentSettingsProps {
  value: AgentSettingsValue;
  providerCapability?: AgentProviderCapability;
  diagnostics?: AgentDiagnosticsValue;
  onChange?: (value: AgentSettingsValue) => void;
}

function safePositiveInteger(value: unknown): number | undefined {
  return typeof value === "number"
    && Number.isSafeInteger(value)
    && value > 0
    ? value
    : undefined;
}

function safeBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function safePermissionMode(value: unknown): AgentPermissionMode {
  return value === "normal" || value === "plan" || value === "bypassPermissions"
    ? value
    : "bypassPermissions";
}

export function fixedAgentServiceSettings(value: AgentSettingsValue): AgentSettingsValue {
  const providerContextWindow = safePositiveInteger(value.provider_context_window);
  const providerSecretConfigured = safeBoolean(value.provider_secret_configured);

  return {
    provider: FARO_PROVIDER,
    model: FARO_MODEL,
    context_window: FARO_CONTEXT_WINDOW,
    permission_mode: safePermissionMode(value.permission_mode),
    workspace_roots: Array.isArray(value.workspace_roots)
      ? value.workspace_roots.filter((root): root is string => typeof root === "string")
      : [],
    mcp_enabled: value.mcp_enabled === true,
    skills_enabled: value.skills_enabled === true,
    subagents_enabled: value.subagents_enabled === true,
    web_enabled: value.web_enabled === true,
    ...(providerContextWindow ? { provider_context_window: providerContextWindow } : {}),
    ...(typeof providerSecretConfigured === "boolean"
      ? { provider_secret_configured: providerSecretConfigured }
      : {}),
  };
}

function formatTokens(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

export function AgentSettings({
  value,
  providerCapability,
  diagnostics = {},
  onChange,
}: AgentSettingsProps) {
  const editable = fixedAgentServiceSettings(value);
  const update = (patch: Partial<AgentSettingsValue>) => {
    onChange?.(fixedAgentServiceSettings({ ...editable, ...patch }));
  };
  const requestedContext = FARO_CONTEXT_WINDOW;
  const actualContext = providerCapability?.contextWindow
    ?? safePositiveInteger(value.provider_context_window);
  const secretConfigured = providerCapability?.secretConfigured
    ?? safeBoolean(value.provider_secret_configured)
    ?? false;
  const capabilityReduced = typeof actualContext === "number"
    && actualContext < requestedContext;

  return (
    <section aria-labelledby="agent-settings-heading" className={styles.settings}>
      <header className={styles.settingsHeader}>
        <span className={styles.eyebrow}>AI 助教服务</span>
        <h2 id="agent-settings-heading">服务设置</h2>
        <p>对话固定通过 Faro 中转站连接 Gemini，不提供其他服务商切换。</p>
      </header>

      <div aria-label="固定 AI 服务" className={styles.serviceGrid}>
        <div className={styles.serviceCard}>
          <span>Provider</span>
          <strong>Faro</strong>
          <small>固定中转服务</small>
        </div>
        <div className={styles.serviceCard}>
          <span>Model</span>
          <strong>{FARO_MODEL}</strong>
          <small>Gemini 3.7 Flash</small>
        </div>
        <div className={styles.serviceCard}>
          <span>Context window</span>
          <strong>{formatTokens(FARO_CONTEXT_WINDOW)} tokens</strong>
          <small>由服务端统一管理</small>
        </div>
      </div>

      <div className={styles.secretState}>
        <span>Faro API key</span>
        <strong>{secretConfigured ? "configured" : "not-configured"}</strong>
      </div>

      {capabilityReduced ? (
        <p className={styles.capabilityNotice} role="status">
          Provider 实际 context window：{formatTokens(actualContext)} tokens；请求值 {formatTokens(requestedContext)}。
        </p>
      ) : null}

      {editable.permission_mode === "bypassPermissions" ? (
        <p className={styles.permissionWarning} role="alert">
          bypassPermissions 允许 Agent 在宿主机执行命令并修改已授权工作区；请持续核对 workspace roots 和审计记录。
        </p>
      ) : null}

      <div className={styles.settingsGrid}>
        <label className={styles.field}>
          <span>Permission mode</span>
          <select
            aria-label="Permission mode"
            disabled={!onChange}
            onChange={(event) => update({ permission_mode: event.target.value as AgentPermissionMode })}
            value={editable.permission_mode}
          >
            <option value="bypassPermissions">bypassPermissions</option>
            <option value="normal">normal</option>
            <option value="plan">plan</option>
          </select>
        </label>
      </div>

      <section className={styles.roots} aria-labelledby="workspace-roots-heading">
        <h3 id="workspace-roots-heading">Workspace roots</h3>
        {(editable.workspace_roots?.length ?? 0) > 0 ? (
          <ul>
            {editable.workspace_roots?.map((root) => <li key={root}>{root}</li>)}
          </ul>
        ) : <p>No workspace roots configured</p>}
        {onChange ? (
          <label className={styles.field}>
            <span>Edit workspace roots (one per line)</span>
            <textarea
              aria-label="Edit workspace roots"
              onChange={(event) => update({
                workspace_roots: event.target.value
                  .split(/\r?\n/)
                  .map((root) => root.trim())
                  .filter(Boolean),
              })}
              value={editable.workspace_roots?.join("\n") ?? ""}
            />
          </label>
        ) : null}
      </section>

      <fieldset className={styles.capabilities}>
        <legend>Capabilities</legend>
        <p className={styles.capabilityHelp}>
          这些开关是当前浏览器中的工作区偏好，刷新后仍会保留；固定的 Faro、Gemini 3.7 Flash 和 32,000 tokens 不受影响。
        </p>
        {([
          ["MCP", "mcp_enabled"],
          ["Skills", "skills_enabled"],
          ["Subagents", "subagents_enabled"],
          ["Web", "web_enabled"],
        ] as const).map(([label, key]) => (
          <label key={key}>
            <input
              aria-label={label}
              checked={editable[key] === true}
              disabled={!onChange}
              onChange={(event) => update({ [key]: event.target.checked })}
              type="checkbox"
            />
            <span>{label}</span>
          </label>
        ))}
      </fieldset>

      <AgentDiagnostics value={diagnostics} />
    </section>
  );
}