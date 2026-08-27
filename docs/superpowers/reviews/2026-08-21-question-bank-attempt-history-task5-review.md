# Question Bank Task 5 — Owner Attempt History Review

- **Date:** 2026-08-21
- **Scope:** `GET /api/v1/knowledge-bases/{knowledge_base_id}/question-versions/{question_version_id}/attempt-history`
- **Result:** **SPEC PASS; QUALITY/SECURITY PASS**
- **Review mode:** independent, read-only SPEC and QUALITY/SECURITY reviews. Reviewers made no source, test, documentation, Git-state, Docker, Compose, Alembic, full-suite, coverage, or external-service changes.

## Contract and focused verification

The Task 5 endpoint is a bounded, owner-only, read-only history view of immutable assessment evidence for one question version:

- it first authorizes readable access to the requested knowledge base, then hides unknown, cross-knowledge-base, cross-space, and inaccessible versions behind `404`;
- it returns only `QuestionAttemptAssessment` rows belonging to the current user, but returns that user's complete assessment history rather than Task 4's latest-only review projection;
- the public `attempted_at` is taken from `QuestionAttempt.created_at`, not assessment creation time;
- results are newest first by `(attempted_at DESC, assessment.id DESC)` and use the same two values in a validated, opaque keyset cursor;
- pagination is bounded to `limit` 1..50 (default 20), uses `limit + 1` lookahead, and has neither offset pagination, total counts, nor unbounded export;
- the envelope exposes only the planned safe assessment fields. It omits submitted answers, expected answers/keywords, grading rubrics, provenance, document/user/space/knowledge-base identifiers, request hashes, internal attempt/assessment IDs, and streak fields;
- `QuestionAttempt` contributes only its `created_at` scalar. Participating assessment, version, and question ORM entities use `load_only(...)`, so private columns are not ordinarily loaded merely to be omitted from the response;
- the GET path has no creation, scoring, mutation, flush, or other write operation.

After the independent SPEC review identified a non-blocking test-coverage P2, the focused pagination test was minimally strengthened: three attempts are assigned the same `attempted_at`; the test records their descending internal assessment order through three distinct *public* `review_due_at` markers; two keyset pages are joined and must return every public marker in the expected order exactly once. This proves the secondary `assessment.id DESC` key prevents duplicates and skips without exposing the internal ID in the API response.

Controller verification completed:

```text
E:\项目\知识库课本\.worktrees\platform-foundation\apps\api\.venv\Scripts\python.exe -B -m pytest tests\test_question_bank.py -p no:cacheprovider -q
23 passed
```

```text
ruff check --no-cache <Task 5 allowed files>
All checks passed!
```

```text
untracked four-file no-index whitespace check
PASS
```

The focused pytest run emitted only existing non-blocking Starlette/httpx TestClient and `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warnings.

## Independent review outcomes

### Specification review

**PASS — no P0 or P1.** The reviewer confirmed the route, authorization order, 404 concealment, current-user isolation, complete-history semantics, attempt-time public timestamp, matching keyset predicate/order, `limit + 1`, safe DTO/envelope projection, deferred private ORM columns, and read-only behavior.

The initial reviewer observation was a P2 test gap for equal `attempted_at` values. It was not an implementation defect. The focused test above closes that coverage gap.

### Quality and security review

**PASS — no P0 or P1.** The independent reviewer confirmed:

- safe column projection and DTO mapping, with the assessment ID retained only inside the opaque continuation cursor;
- cursor rejection for empty/oversized values, invalid Base64/JSON/shape/UUID, and timezone-naive timestamps, while normalizing accepted timestamps to UTC;
- consistent user, knowledge-base, and space predicates over assessment, attempt, version, and question joins;
- no write effect in the GET path;
- exact agreement between the descending `(attempted_at, assessment.id)` sort and continuation predicate; and
- meaningful equal-timestamp cross-page regression coverage using only public markers.

### Whitespace-check qualification

All four Task 5 allowed files are currently untracked in this worktree. A normal `git diff --check -- <path>` would therefore not inspect their content. The controller instead ran `git diff --no-index --check -- NUL <path>` for each allowed file; no whitespace diagnostics were emitted. Because `--no-index` returns a content-difference exit code even when whitespace is clean, the command was interpreted by its emitted diagnostics rather than by a zero exit code.

This is a whitespace-only check, not a semantic/security validation. The final semantic result is based on the independent source/test reviews and focused verification above.

## Verification boundary and retained limitations

This slice did not run Docker/Compose, Alembic migration operations, the full test suite, coverage, real PostgreSQL concurrency or performance testing, or external API calls. It did not modify Task 10 files or reopen Task 3A/Task 3B stop-rule exceptions.

Task 5 is complete for its scoped contract. **Phase 5 remains `in_progress`**, and Task 10 remains **blocked/abandoned**.