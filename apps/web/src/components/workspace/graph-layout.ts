import type { KnowledgeGraphNode } from "../../lib/knowledge-api";

export type GraphLayoutNode = Pick<KnowledgeGraphNode, "id" | "title">;

export type GraphLayoutPosition = {
  x: number;
  y: number;
};

const INSET = 48;
const NODES_PER_RING = 8;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

export function layoutGraph(
  nodes: readonly GraphLayoutNode[],
  width: number,
  height: number,
): Map<string, GraphLayoutPosition> {
  const sortedNodes = [...nodes].sort((left, right) =>
    left.id < right.id ? -1 : left.id > right.id ? 1 : 0,
  );
  const positions = new Map<string, GraphLayoutPosition>();
  if (sortedNodes.length === 0) return positions;

  const insetX = Math.min(INSET, Math.max(0, width / 2));
  const insetY = Math.min(INSET, Math.max(0, height / 2));
  const centerX = width / 2;
  const centerY = height / 2;
  positions.set(sortedNodes[0].id, {
    x: clamp(centerX, insetX, width - insetX),
    y: clamp(centerY, insetY, height - insetY),
  });

  const outerRing = Math.ceil((sortedNodes.length - 1) / NODES_PER_RING);
  const maxRadius = Math.max(0, Math.min(width / 2 - insetX, height / 2 - insetY));
  for (let index = 1; index < sortedNodes.length; index += 1) {
    const ring = Math.ceil(index / NODES_PER_RING);
    const ringStart = (ring - 1) * NODES_PER_RING + 1;
    const nodesInRing = Math.min(NODES_PER_RING, sortedNodes.length - ringStart);
    const angle = ((index - ringStart) / nodesInRing) * Math.PI * 2 - Math.PI / 2;
    const radius = (maxRadius * ring) / outerRing;
    positions.set(sortedNodes[index].id, {
      x: clamp(centerX + Math.cos(angle) * radius, insetX, width - insetX),
      y: clamp(centerY + Math.sin(angle) * radius, insetY, height - insetY),
    });
  }

  return positions;
}
