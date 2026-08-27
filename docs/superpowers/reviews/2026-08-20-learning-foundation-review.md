# Learning Foundation Review Record — 2026-08-20

## Scope

Reviewed only the new pure-Python `tutor_api.learning` slice and its focused tests. No Docker/Compose, database/API/LLM integration, full test suite, coverage gate, or Task 10 code was run or modified.

## Implemented scope

- deterministic server-owned answer grading for choice, short, and keyword-based open questions;
- bounded recency-weighted mastery estimate;
- deterministic spaced-review scheduling;
- deterministic next-step priority policy;
- immutable dataclass contracts and focused tests.

## Verification evidence

Command run from `apps/api`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_learning_grading.py tests\test_learning_mastery.py tests\test_learning_policy.py -q
.\.venv\Scripts\python.exe -m ruff check --no-cache src\tutor_api\learning tests\test_learning_grading.py tests\test_learning_mastery.py tests\test_learning_policy.py
git -C E:\项目\知识库课本\.worktrees\platform-foundation diff --check -- apps/api/src/tutor_api/learning apps/api/tests/test_learning_grading.py apps/api/tests/test_learning_mastery.py apps/api/tests/test_learning_policy.py
```

Observed result: **30 passed**; Ruff passed; focused diff check passed. Pytest also emitted a non-functional `PytestCacheWarning` because the pre-existing `.pytest_cache` directory denied cache writes (`WinError 5`). Test assertions all passed; no permissions workaround was added.

## Independent reviews

1. First independent SPEC review reported three contract gaps: SHORT case-folding, mutable containers retained by frozen contracts, and an unrestricted choice answer key.
2. One targeted spec correction was made. Independent SPEC re-review: **SPEC PASS**.
3. Independent QUALITY/SECURITY review then identified public input validation gaps. One targeted quality correction was made (strict booleans/integers/time values, immutable keyword snapshots, public result validation). The subsequent focused verification passed.
4. QUALITY/SECURITY re-review: **FAIL, one Minor finding only**.

### Remaining stop-rule exception

`QuestionSpec` still permits an OPEN question to receive a non-string mutable value in `expected_answer`; because OPEN grading ignores that field, a caller-owned list/dict can remain reachable despite the frozen dataclass. The reviewer identified this as the same frozen-contract immutability rule already corrected once for `expected_keywords` and `ReviewPolicy`.

Per the explicit project stop rule—initial attempt plus one targeted correction maximum for the same acceptance rule—no third fix was made. Therefore this slice is **not quality/security approved** and must not be reported as complete. The actual remaining failure is low-impact within the current pure domain slice but remains recorded for a later deliberately scoped contract cleanup.

## Status

- **SPEC:** PASS
- **QUALITY/SECURITY:** FAIL (stopped under the one-correction rule)
- **Phase 5:** still in progress
- **Task 10:** unchanged and still blocked/abandoned
- No files were staged, committed, reset, stashed, or discarded.