import { describe, expect, it } from "vitest";

import { layoutGraph } from "./graph-layout";

describe("layoutGraph", () => {
  it("places twelve readonly nodes inside the 48px canvas inset", () => {
    const nodes = [
      { id: "node-12", title: "Node 1" },
      { id: "node-11", title: "Node 2" },
      { id: "node-10", title: "Node 3" },
      { id: "node-09", title: "Node 4" },
      { id: "node-08", title: "Node 5" },
      { id: "node-07", title: "Node 6" },
      { id: "node-06", title: "Node 7" },
      { id: "node-05", title: "Node 8" },
      { id: "node-04", title: "Node 9" },
      { id: "node-03", title: "Node 10" },
      { id: "node-02", title: "Node 11" },
      { id: "node-01", title: "Node 12" },
    ] as const;

    const positions = layoutGraph(nodes, 800, 520);

    expect(positions).toHaveLength(12);
    expect(positions.get("node-01")).toEqual({ x: 400, y: 260 });
    for (const position of positions.values()) {
      expect(position.x).toBeGreaterThanOrEqual(48);
      expect(position.x).toBeLessThanOrEqual(752);
      expect(position.y).toBeGreaterThanOrEqual(48);
      expect(position.y).toBeLessThanOrEqual(472);
    }
  });

  it("keeps empty, singleton, and multi-node layouts finite within tiny canvases", () => {
    expect(layoutGraph([], 0, 0)).toEqual(new Map());

    const cases = [
      { nodes: [{ id: "one", title: "One" }], width: 0, height: 0 },
      { nodes: [{ id: "one", title: "One" }], width: 40, height: 40 },
      {
        nodes: [
          { id: "three", title: "Three" },
          { id: "one", title: "One" },
          { id: "two", title: "Two" },
        ],
        width: 40,
        height: 40,
      },
    ] as const;

    for (const { nodes, width, height } of cases) {
      const positions = layoutGraph(nodes, width, height);
      for (const position of positions.values()) {
        expect(Number.isFinite(position.x)).toBe(true);
        expect(Number.isFinite(position.y)).toBe(true);
        expect(position.x).toBeGreaterThanOrEqual(0);
        expect(position.x).toBeLessThanOrEqual(width);
        expect(position.y).toBeGreaterThanOrEqual(0);
        expect(position.y).toBeLessThanOrEqual(height);
      }
    }
  });

  it("uses UTF-16 code-unit ID order for the center node", () => {
    const positions = layoutGraph(
      [
        { id: "Ä", title: "A umlaut" },
        { id: "a", title: "Lowercase a" },
        { id: "Z", title: "Uppercase z" },
      ],
      800,
      520,
    );

    expect(positions.get("Z")).toEqual({ x: 400, y: 260 });
  });
});
