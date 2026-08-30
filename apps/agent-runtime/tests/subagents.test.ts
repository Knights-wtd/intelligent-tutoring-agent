import { SubagentManager } from "../src/subagents/SubagentManager";

it("queues subagents with observable backpressure but no cumulative count cap", async () => {
  let active = 0; let peak = 0;
  const manager = new SubagentManager({ concurrency: 3, run: async request => { active += 1; peak = Math.max(peak, active); await Promise.resolve(); active -= 1; return { text: request.prompt }; } });
  const results = await Promise.all(Array.from({ length: 30 }, (_, index) => manager.run({ parentSessionId: "parent", parentToolCallId: `tool-${index}`, prompt: `p${index}` })));
  expect(results).toHaveLength(30);
  expect(peak).toBeLessThanOrEqual(3);
  expect(manager.diagnostics().completed).toBe(30);
});
