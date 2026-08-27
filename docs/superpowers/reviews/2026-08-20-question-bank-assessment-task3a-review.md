# Question Bank Assessment Task 3A Review

**Date:** 2026-08-20  
**Scope:** `apps/api/src/tutor_api/question_bank/assessment.py` and `apps/api/tests/test_question_bank_assessment.py` only.

## Functional verification

- Focused test: `20 passed`.
- Targeted Ruff: passed.
- Targeted new-file whitespace checks: passed (only existing Git LF-to-CRLF conversion warnings).
- The prior independent specification review passed.

## Quality and security review sequence

The initial quality/security review identified three issues:

1. contradictory direct construction of `AssessmentResult` and `ReviewSchedule`;
2. full materialization of mastery-history iterables;
3. incomplete AST import-isolation coverage for `ImportFrom` imports.

The authorized one-time targeted correction fixed (1) and (2), and expanded the AST helper to cover `from tutor_api.learning.grading import ...`.

The independent re-review confirmed that the pure runtime module currently uses only standard-library imports and that the first two issues are fixed. It nevertheless found a residual P2 regression-test gap:

```python
from tutor_api import learning
```

is represented by `ast.ImportFrom(module="tutor_api", names=["learning"])`. The current helper records only `node.module` for `ImportFrom`, so it would record `tutor_api`, while the test rejects only `tutor_api.learning` and its descendants. A future forbidden import in that form could therefore bypass this particular regression test. Current production code contains no such import.

## Final Task 3A disposition

- **SPEC:** PASS.
- **Focused functional checks:** PASS.
- **QUALITY/SECURITY:** FAIL (residual P2 import-isolation regression-test coverage).
- **Stop-rule evidence:** this is the same `ImportFrom` isolation acceptance rule after its one permitted targeted correction. Do **not** attempt a third fix in Task 3A.

This review does not waive the P2. The result must be carried as a known limitation in later handoff material. A later independently scoped hardening task may replace the regression helper after a fresh explicit acceptance decision; it is not part of this task.

## Boundaries respected

No Docker/Compose/Alembic execution, full suite, coverage gate, Git staging/commit/reset/stash/checkout, Task 10 protected-file modification, or `tutor_api.learning` modification was performed.
