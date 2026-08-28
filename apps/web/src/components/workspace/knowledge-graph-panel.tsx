"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { knowledgeApi, type KnowledgeBase, type KnowledgeGraph, type KnowledgeGraphNode } from "@/lib/knowledge-api";
import { layoutGraph } from "./graph-layout";
import styles from "./workspace-shell.module.css";

const WIDTH = 800;
const HEIGHT = 520;
const MIN_SCALE = 0.4;
const MAX_SCALE = 2.4;
const SCALE_STEP = 0.2;

type Viewport = {
  x: number;
  y: number;
  scale: number;
};

const FIT_VIEWPORT: Viewport = { x: 0, y: 0, scale: 1 };

type Props = {
  knowledgeBase: Pick<KnowledgeBase, "id" | "name">;
  onReviewCandidates?: () => void;
  onOpenNote?: (noteId: string) => void;
};

export function KnowledgeGraphPanel({ knowledgeBase, onReviewCandidates, onOpenNote }: Props) {
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [search, setSearch] = useState("");
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [viewport, setViewport] = useState<Viewport>(FIT_VIEWPORT);
  const [requestNumber, setRequestNumber] = useState(0);
  const dragStart = useRef<{ pointerId: number; clientX: number; clientY: number; x: number; y: number } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    void Promise.resolve().then(() => {
      if (!current || controller.signal.aborted) return;
      setGraph(null);
      setLoading(true);
      setFailed(false);
      setSearch("");
      setFocusedId(null);
      setViewport(FIT_VIEWPORT);
      dragStart.current = null;
    });
    void knowledgeApi.graph(knowledgeBase.id, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setGraph(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [knowledgeBase.id, requestNumber]);

  const positions = useMemo(() => layoutGraph(graph?.nodes ?? [], WIDTH, HEIGHT), [graph]);
  const resolvedEdges = useMemo(() => {
    if (!graph) return [];
    const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
    return graph.edges.flatMap((edge) => {
      const source = nodesById.get(edge.source_id);
      const target = nodesById.get(edge.target_id);
      return source && target && positions.has(source.id) && positions.has(target.id)
        ? [{ edge, source, target }]
        : [];
    });
  }, [graph, positions]);
  const focusedNode = graph?.nodes.find((node) => node.id === focusedId) ?? null;
  const query = search.trim().toLocaleLowerCase("zh-CN");
  const visibleNodes = graph?.nodes.filter(
    (node) => node.title.toLocaleLowerCase("zh-CN").includes(query),
  ) ?? [];
  const transform = `translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`;

  const setScale = (nextScale: number) => {
    setViewport((current) => ({ ...current, scale: clampScale(nextScale) }));
  };

  const selectNode = (node: KnowledgeGraphNode) => {
    setFocusedId(node.id);
    setViewport(focusViewport(positions.get(node.id)));
    if (node.note_id) onOpenNote?.(node.note_id);
  };

  const fitView = () => {
    setFocusedId(null);
    setViewport(FIT_VIEWPORT);
  };

  return (
    <section aria-label="知识关联图" className={styles.knowledgeGraphPanel}>
      <header className={styles.graphHeader}>
        <div><span className={styles.eyebrow}>{knowledgeBase.name}</span><h2>知识关联图</h2></div>
        <div aria-label="图谱视图控制" className={styles.graphControls} role="group">
          <button aria-label="缩小" onClick={() => setScale(viewport.scale - SCALE_STEP)} type="button">−</button>
          <span className={styles.graphScale}>{Math.round(viewport.scale * 100)}%</span>
          <button aria-label="放大" onClick={() => setScale(viewport.scale + SCALE_STEP)} type="button">＋</button>
          <button aria-label="100%" onClick={() => setViewport(FIT_VIEWPORT)} type="button">重置</button>
          <button onClick={fitView} type="button">适应视图</button>
        </div>
      </header>
      {loading ? <p role="status">正在加载关联图…</p> : null}
      {!loading && failed ? (
        <div className={styles.graphMessage}>
          <p role="alert">关联图暂时无法加载，请重试。</p>
          <button onClick={() => setRequestNumber((value) => value + 1)} type="button">重试</button>
        </div>
      ) : null}
      {!loading && !failed && graph?.nodes.length === 0 ? (
        <div className={styles.graphEmptyState}>
          <p>还没有已确认的知识节点。</p>
          {onReviewCandidates ? <button onClick={onReviewCandidates} type="button">审核候选内容</button> : null}
        </div>
      ) : null}
      {!loading && !failed && graph && graph.nodes.length > 0 ? (
        <div className={styles.graphWorkspace}>
          <div
            className={styles.graphCanvas}
            data-testid="graph-canvas"
            onPointerDown={(event) => {
              dragStart.current = {
                pointerId: event.pointerId,
                clientX: event.clientX,
                clientY: event.clientY,
                x: viewport.x,
                y: viewport.y,
              };
              event.currentTarget.setPointerCapture?.(event.pointerId);
            }}
            onPointerMove={(event) => {
              const start = dragStart.current;
              if (!start || start.pointerId !== event.pointerId) return;
              setViewport((current) => ({
                ...current,
                x: start.x + event.clientX - start.clientX,
                y: start.y + event.clientY - start.clientY,
              }));
            }}
            onPointerUp={(event) => {
              if (dragStart.current?.pointerId === event.pointerId) dragStart.current = null;
              event.currentTarget.releasePointerCapture?.(event.pointerId);
            }}
            onWheel={(event) => {
              event.preventDefault();
              setScale(viewport.scale + (event.deltaY < 0 ? SCALE_STEP : -SCALE_STEP));
            }}
          >
            <svg aria-label={`${knowledgeBase.name}关联图`} role="img" viewBox={`0 0 ${WIDTH} ${HEIGHT}`}>
              <g data-testid="graph-viewport" transform={transform}>
                <g data-testid="graph-edges">
                  {resolvedEdges.map(({ edge, source, target }) => {
                    const sourcePosition = positions.get(source.id);
                    const targetPosition = positions.get(target.id);
                    return sourcePosition && targetPosition ? (
                      <line
                        key={edge.id}
                        x1={sourcePosition.x}
                        x2={targetPosition.x}
                        y1={sourcePosition.y}
                        y2={targetPosition.y}
                      />
                    ) : null;
                  })}
                </g>
                <g data-testid="graph-nodes">
                  {graph.nodes.map((node) => {
                    const position = positions.get(node.id);
                    return position ? (
                      <g className={styles.graphNode} key={node.id} onClick={() => selectNode(node)}>
                        <circle className={node.id === focusedId ? styles.graphNodeFocused : undefined} cx={position.x} cy={position.y} r="12" />
                        <text x={position.x} y={position.y + 30}>{node.title}</text>
                      </g>
                    ) : null;
                  })}
                </g>
              </g>
            </svg>
          </div>
          <aside className={styles.graphSidebar}>
            <label className={styles.graphSearchLabel}>搜索节点
              <input aria-label="搜索节点" onChange={(event) => setSearch(event.target.value)} role="searchbox" type="search" value={search} />
            </label>
            <ul aria-label="关联图节点" className={styles.graphNodeList}>
              {visibleNodes.map((node) => (
                <li key={node.id}><button aria-pressed={node.id === focusedId} onClick={() => selectNode(node)} type="button">{node.title}</button></li>
              ))}
            </ul>
            <ul aria-label="关联关系">
              {resolvedEdges.map(({ edge, source, target }) => (
                <li key={edge.id}>
                  {source.title} → {target.title} · 关系：{edge.relation} · 类型：{edge.kind} ·
                  来源：{edge.source_pointer}
                </li>
              ))}
            </ul>
            {visibleNodes.length === 0 ? <p>没有匹配的节点。</p> : null}
            {focusedNode ? <NodeDetails node={focusedNode} /> : null}
          </aside>
        </div>
      ) : null}
    </section>
  );
}

function NodeDetails({ node }: { node: KnowledgeGraphNode }) {
  return (
    <section aria-label="节点详情" className={styles.graphDetails}>
      <h3>{node.title}</h3><p>类型：{node.kind}</p><strong>来源指针</strong>
      {node.source_pointers.length > 0 ? (
        <ul>{node.source_pointers.map((pointer) => <li key={pointer}>{pointer}</li>)}</ul>
      ) : <p>暂无来源指针。</p>}
    </section>
  );
}

function clampScale(scale: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, Math.round(scale * 10) / 10));
}

function focusViewport(position: { x: number; y: number } | undefined): Viewport {
  if (!position) return FIT_VIEWPORT;
  const scale = 1.4;
  return {
    x: WIDTH / 2 - position.x * scale,
    y: HEIGHT / 2 - position.y * scale,
    scale,
  };
}
