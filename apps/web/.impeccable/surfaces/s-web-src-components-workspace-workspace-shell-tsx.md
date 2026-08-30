---
version: 1
slug: "s-web-src-components-workspace-workspace-shell-tsx"
primary_target: "apps/web/src/components/workspace/workspace-shell.tsx"
related_targets: ["apps/web/src/components/workspace/workspace-shell.module.css","apps/web/src/components/workspace/knowledge-panel.tsx","apps/web/src/components/workspace/question-bank-panel.tsx"]
---

Scope: personal learning workspace shell and its knowledge-base, task, graph, and tutor surfaces.
Mode: Operate.
Audience: individual learners maintaining long-lived textbook knowledge bases.
Primary job: resume the last learning activity, then work through due review items.
Primary action: continue learning.
Core content: knowledge-base list, ordered learning queue, reading/practice/search tabs, confirmed knowledge graph, source-backed tutor context.
Constraints: knowledge bases are the leftmost primary navigation; every knowledge-base row separates selection from its graph button; classroom features are secondary; no fake buttons; model keys remain server-side.
Chosen direction: C, the Obsidian-inspired review inbox. Neutral editor surfaces, one purple accent, fine borders, compact rows, central tabs, and a right contextual tutor.
Memorable moment: opening a knowledge base graph from its row without losing the current task, while the tutor context follows the graph.
Unresolved: exact graph endpoint shape, graph renderer library or native implementation, and final token values after the first build.
