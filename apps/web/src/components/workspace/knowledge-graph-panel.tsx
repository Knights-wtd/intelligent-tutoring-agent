"use client";

import { useEffect, useMemo, useState } from "react";
import { knowledgeApi, type KnowledgeBase, type KnowledgeGraph, type KnowledgeGraphNode } from "@/lib/knowledge-api";
import { layoutGraph } from "./graph-layout";
import styles from "./workspace-shell.module.css";

const WIDTH = 800;
const HEIGHT = 520;
const FIT = "translate(0 0) scale(1)";

type Props = {
  knowledgeBase: Pick<KnowledgeBase, "id" | "name">;
  onReviewCandidates?: () => void;
};

export function KnowledgeGraphPanel({ knowledgeBase, onReviewCandidates }: Props) {
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [search, setSearch] = useState("");
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [requestNumber, setRequestNumber] = useState(0);

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
  const transform = focusedNode ? focusTransform(positions.get(focusedNode.id)) : FIT;

  return (
    <section aria-label="知识关联图" className={styles.knowledgeGraphPanel}>
      <header className={styles.graphHeader}>
        <div><span className={styles.eyebrow}>{knowledgeBase.name}</span><h2>知识关联图</h2></div>
        <button onClick={() => setFocusedId(null)} type="button">适应视图</button>
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
          <div className={styles.graphCanvas}>
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
                      <g key={node.id}>
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
                <li key={node.id}><button aria-pressed={node.id === focusedId} onClick={() => setFocusedId(node.id)} type="button">{node.title}</button></li>
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

function focusTransform(position: { x: number; y: number } | undefined): string {
  if (!position) return FIT;
  const scale = 1.35;
  return `translate(${WIDTH / 2 - position.x * scale} ${HEIGHT / 2 - position.y * scale}) scale(${scale})`;
}
