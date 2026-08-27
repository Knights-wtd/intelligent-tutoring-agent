# Learning Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a small, deterministic learning-domain foundation for Phase 5/Milestone 4 without importing DeepTutor runtime, persistence, permissions, or provider code.

**Architecture:** Keep this slice as pure Python domain logic under `tutor_api.learning`. It accepts server-owned answer keys and learner-state snapshots, returns immutable result objects, and has no database, HTTP, LLM, filesystem, or external dependency. Later SQL/API/Agent tasks will consume these contracts.

**Tech Stack:** Python 3.12, standard library dataclasses/enums/math/re.

**Stop rule:** The first implementation attempt and one targeted correction are the maximum attempts for any single acceptance rule. If the same rule still fails after that correction, mark it blocked with the observed failure and do not keep tuning thresholds.

---

### Task 1: Deterministic grading contracts

**Files:**
- Create: `apps/api/src/tutor_api/learning/__init__.py`
- Create: `apps/api/src/tutor_api/learning/models.py`
- Create: `apps/api/src/tutor_api/learning/grading.py`
- Test: `apps/api/tests/test_learning_grading.py`

- [ ] **Step 1: Write failing tests**

Cover only the public contract:

```python
def test_choice_grading_uses_server_answer_key_and_normalizes_label(): ...
def test_short_grading_is_exact_after_safe_normalization(): ...
def test_open_grading_returns_needs_review_when_keywords_are_insufficient(): ...
def test_empty_answer_is_metacognitive_error(): ...
def test_grading_rejects_blank_question_type_and_missing_answer_key(): ...
```

The test must assert that the public result contains `correct`, `score`, `error_type`, and `needs_review`, but never exposes the server answer key.

- [ ] **Step 2: Run only the new test file and confirm the expected import failure**

Run from `apps/api`:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_learning_grading.py -q
```

Expected: collection fails because `tutor_api.learning` does not exist.

- [ ] **Step 3: Implement the minimum domain types and grader**

Use frozen dataclasses and string enums. Supported public question types are `choice`, `short`, and `open`. Normalize Unicode with NFC, trim outer whitespace, and collapse internal whitespace only for short text; do not perform broad fuzzy matching. Choice accepts a single label (`A`/`a`) and compares to the server-owned key. Open answers use an explicit keyword list supplied by the server and return `needs_review=True` unless the result is unambiguously complete; no LLM call is made.

- [ ] **Step 4: Run the focused tests and Ruff**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_learning_grading.py -q
.venv\Scripts\python.exe -m ruff check --no-cache src/tutor_api/learning tests/test_learning_grading.py
```

- [ ] **Step 5: Stop/review gate**

Record the exact result. One targeted correction is allowed for a failing rule; a second failure blocks that rule rather than adding fuzzy heuristics.

---

### Task 2: Mastery and review scheduling

**Files:**
- Create: `apps/api/src/tutor_api/learning/mastery.py`
- Create: `apps/api/src/tutor_api/learning/scheduler.py`
- Modify: `apps/api/src/tutor_api/learning/models.py`
- Test: `apps/api/tests/test_learning_mastery.py`

- [ ] **Step 1: Write failing tests**

Cover: empty history returns zero; recent attempts have greater weight; one or two correct attempts cannot report full mastery; enough consecutive evidence can reach the configured gate; correct outcomes advance review intervals; incorrect outcomes back off; invalid timestamps/knowledge types are rejected.

- [ ] **Step 2: Run the focused file and verify missing-module failure**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_learning_mastery.py -q
```

- [ ] **Step 3: Implement bounded deterministic formulas**

Keep thresholds and intervals in explicit `ReviewPolicy` data, not scattered constants. Return `MasteryResult` and `ReviewSchedule` with evidence counts and next due time. Do not claim semantic certainty beyond the evidence supplied.

- [ ] **Step 4: Run focused tests and Ruff**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_learning_mastery.py -q
.venv\Scripts\python.exe -m ruff check --no-cache src/tutor_api/learning tests/test_learning_mastery.py
```

- [ ] **Step 5: Stop/review gate**

Apply the same one-correction limit per rule; do not tune formulas repeatedly to chase an arbitrary coverage number.

---

### Task 3: Next learning step policy

**Files:**
- Create: `apps/api/src/tutor_api/learning/policy.py`
- Test: `apps/api/tests/test_learning_policy.py`

- [ ] **Step 1: Write failing tests**

Assert the deterministic priority order: current pending interaction, due review, earliest not-mastered course objective, then completed. Assert that the output contains only opaque IDs and action metadata, not answer keys or raw private content.

- [ ] **Step 2: Implement the pure selector**

Inputs are learner snapshot, pending interaction, due reviews, and ordered course objectives. Filter by the caller-provided learner/space snapshot before selection; do not perform authorization inside this pure function.

- [ ] **Step 3: Run focused tests and Ruff**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_learning_policy.py -q
.venv\Scripts\python.exe -m ruff check --no-cache src/tutor_api/learning tests/test_learning_policy.py
```

- [ ] **Step 4: Stop/review gate**

If the same priority rule fails after one correction, stop and record the rule as blocked.

---

### Task 4: Two-stage review and integration record

**Files:**
- Modify: `task_plan.md`, `findings.md`, `progress.md`
- Review: all files from Tasks 1–3

- [ ] **Step 1: Independent specification review**
- [ ] **Step 2: Fix only confirmed specification gaps, then re-review**
- [ ] **Step 3: Independent quality/security review**
- [ ] **Step 4: Run only focused learning tests, targeted Ruff, and `git diff --check`**
- [ ] **Step 5: Record exact results and remaining SQL/API/LLM work**

**Explicit non-goals for this plan:** no DeepTutor source copy, no SQL migration, no public endpoint, no real provider key, no Agent Loop, no full Phase 5 completion claim.


## Execution record — 2026-08-20

- Implemented the first pure-Python learning slice and its three focused test modules.
- Initial targeted verification: 22 passed; Ruff initially reported formatting-only E501 findings, which were corrected without logic changes.
- Independent SPEC review initially failed on three contracts; after one targeted correction, the independent re-review returned **SPEC PASS**.
- Independent QUALITY/SECURITY review identified input-type and frozen-container issues. After one targeted correction, 30 focused tests, targeted Ruff, and focused `git diff --check` passed.
- QUALITY/SECURITY re-review still found one Minor instance of the same frozen-container rule: OPEN `expected_answer` accepts a caller-owned mutable non-string object. Under the project stop rule, do not apply a third correction to that same rule.
- This plan is therefore **not complete**. The code remains an uncommitted, reviewed-but-quality-exception learning-domain slice; do not claim it completes Phase 5 or use it as a release-quality contract without a future explicitly approved cleanup task.
