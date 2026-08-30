"use client";

import { useEffect, useMemo, useState } from "react";

import { agentApi } from "@/lib/agent-api";
import type { AgentSidecarReference } from "@/lib/agent-events";

import styles from "./agent-tools.module.css";

export interface SidecarByteRange {
  start: number;
  end: number;
}

export type AgentSidecarLoader = (
  sidecar: AgentSidecarReference,
  range: SidecarByteRange,
  signal: AbortSignal,
) => Promise<Response>;

export interface AgentSidecarPreviewProps {
  sidecar: AgentSidecarReference;
  load?: AgentSidecarLoader;
  chunkSize?: number;
  renderWindowBytes?: number;
}

const DEFAULT_CHUNK_SIZE = 64 * 1024;
const DEFAULT_RENDER_WINDOW = 16 * 1024;

const defaultLoad: AgentSidecarLoader = (sidecar, range, signal) =>
  agentApi.sidecar(sidecar.id, {
    range: `bytes=${range.start}-${range.end}`,
    signal,
  });

function concatenate(left: Uint8Array, right: Uint8Array): Uint8Array {
  const combined = new Uint8Array(left.length + right.length);
  combined.set(left);
  combined.set(right, left.length);
  return combined;
}

function contentRange(response: Response): { start: number; end: number; total: number } | null {
  const value = response.headers.get("Content-Range");
  const match = value?.match(/^bytes (\d+)-(\d+)\/(\d+)$/i);
  if (!match) return null;
  return {
    start: Number(match[1]),
    end: Number(match[2]),
    total: Number(match[3]),
  };
}

function decode(bytes: Uint8Array): string {
  return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
}

function previewText(
  bytes: Uint8Array,
  mediaType: string,
  complete: boolean,
): string {
  const text = decode(bytes);
  if (complete && mediaType.toLowerCase().includes("json")) {
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      return text;
    }
  }
  return text;
}

function safePositiveInteger(value: number | undefined, fallback: number): number {
  return Number.isSafeInteger(value) && (value ?? 0) > 0 ? value as number : fallback;
}

function SidecarStream({
  sidecar,
  load = defaultLoad,
  chunkSize,
  renderWindowBytes,
}: AgentSidecarPreviewProps) {
  const requestedChunkSize = safePositiveInteger(chunkSize, DEFAULT_CHUNK_SIZE);
  const windowSize = safePositiveInteger(renderWindowBytes, DEFAULT_RENDER_WINDOW);
  const [bytes, setBytes] = useState(() => new Uint8Array());
  const [totalBytes, setTotalBytes] = useState(sidecar.size);
  const [complete, setComplete] = useState(sidecar.size === 0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [windowStart, setWindowStart] = useState(0);

  async function loadRange(start: number, signal: AbortSignal) {
    if (loading || complete) return;
    setLoading(true);
    setError(null);
    try {
      const end = Math.max(start, Math.min(totalBytes - 1, start + requestedChunkSize - 1));
      const response = await load(sidecar, { start, end }, signal);
      const range = contentRange(response);
      const chunk = new Uint8Array(await response.arrayBuffer());
      setBytes((current) => start === 0 ? chunk : concatenate(current, chunk));
      const resolvedTotal = range?.total ?? totalBytes;
      const loadedThrough = range ? range.end + 1 : start + chunk.length;
      setTotalBytes(resolvedTotal);
      setComplete(response.status === 200 || loadedThrough >= resolvedTotal || chunk.length === 0);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setError(caught instanceof Error ? caught.message : "Sidecar 加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => {
      if (sidecar.size > 0 && !controller.signal.aborted) {
        void loadRange(0, controller.signal);
      }
    });
    return () => controller.abort();
    // The keyed stream owns one sidecar identity. Loader/options are deliberately captured here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sidecar.id, sidecar.size]);

  const visibleEnd = Math.min(bytes.length, windowStart + windowSize);
  const visibleBytes = useMemo(
    () => bytes.slice(windowStart, visibleEnd),
    [bytes, visibleEnd, windowStart],
  );
  const rendered = previewText(
    visibleBytes,
    sidecar.mediaType,
    complete && windowStart === 0 && visibleEnd === bytes.length,
  );
  const hasPreviousWindow = windowStart > 0;
  const hasNextWindow = visibleEnd < bytes.length;
  const htmlAsText = sidecar.mediaType.toLowerCase().includes("html");

  return (
    <section className={styles.sidecarPreview} data-testid={`agent-sidecar-${sidecar.id}`}>
      <header className={styles.sidecarHeader}>
        <div>
          <strong>Sidecar</strong>
          <span>{sidecar.mediaType}</span>
        </div>
        <a
          className={styles.downloadLink}
          download
          href={`/api/v1/agent/sidecars/${encodeURIComponent(sidecar.id)}`}
        >
          下载完整内容
        </a>
      </header>

      <dl className={styles.sidecarFacts}>
        <div><dt>大小</dt><dd>{sidecar.size} bytes</dd></div>
        <div><dt>哈希</dt><dd>SHA-256 {sidecar.sha256}</dd></div>
      </dl>

      {htmlAsText ? <p className={styles.safetyNote}>HTML 以纯文本安全显示</p> : null}
      {error ? <p className={styles.error} role="alert">{error}</p> : null}

      <pre className={styles.sidecarContent}>{rendered}</pre>

      {bytes.length > windowSize ? (
        <div className={styles.windowControls}>
          <span>预览窗口 {windowStart + 1}–{visibleEnd} / {bytes.length} bytes</span>
          <div>
            <button
              disabled={!hasPreviousWindow}
              onClick={() => setWindowStart(Math.max(0, windowStart - windowSize))}
              type="button"
            >
              上一预览窗口
            </button>
            <button
              disabled={!hasNextWindow}
              onClick={() => setWindowStart(Math.min(bytes.length - 1, windowStart + windowSize))}
              type="button"
            >
              下一预览窗口
            </button>
          </div>
        </div>
      ) : null}

      <footer className={styles.sidecarFooter}>
        <span>
          {complete
            ? `完整内容已加载 · ${bytes.length} bytes`
            : `已加载 ${bytes.length} / ${totalBytes} bytes`}
        </span>
        {!complete ? (
          <button
            disabled={loading}
            onClick={() => {
              const controller = new AbortController();
              void loadRange(bytes.length, controller.signal);
            }}
            type="button"
          >
            {loading ? "加载中…" : "加载更多"}
          </button>
        ) : null}
      </footer>
    </section>
  );
}
export function AgentSidecarPreview(props: AgentSidecarPreviewProps) {
  return (
    <SidecarStream
      key={`${props.sidecar.id}:${props.sidecar.size}:${props.sidecar.sha256}`}
      {...props}
    />
  );
}
