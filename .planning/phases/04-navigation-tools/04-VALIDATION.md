---
phase: 4
slug: navigation-tools
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-28
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python `unittest` |
| **Config file** | none |
| **Quick run command** | `python -m unittest backend.tests.test_prd_smoke -v` |
| **Full suite command** | `python -m unittest backend.tests.test_prd_smoke -v` |
| **Estimated runtime** | ~10-20 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m unittest backend.tests.test_prd_smoke -v`
- **After every plan wave:** Run `python -m unittest backend.tests.test_prd_smoke -v`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | TOOL-01 | backend smoke | `python -m unittest backend.tests.test_prd_smoke -v` | ✅ | ⬜ pending |
| 04-01-02 | 01 | 1 | TOOL-02 | backend smoke | `python -m unittest backend.tests.test_prd_smoke -v` | ✅ | ⬜ pending |
| 04-02-01 | 02 | 2 | TOOL-01 | backend smoke | `python -m unittest backend.tests.test_prd_smoke -v` | ✅ | ⬜ pending |
| 04-02-02 | 02 | 2 | TOOL-02 | backend smoke | `python -m unittest backend.tests.test_prd_smoke -v` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Add or extend direct automated coverage for `execute_ls()` root-path, scoped-path, and invalid-path behavior.
- [ ] Add or extend direct automated coverage for `execute_tree()` depth, limit, truncation, and visibility behavior.
- [ ] Verify explorer integration still calls the stable `ls`/`tree` contracts after any navigation changes.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Explorer/chat UX remains sensible after navigation-tool changes | TOOL-01, TOOL-02 | No dedicated deterministic end-to-end explorer-loop test exists yet | Ask the chat to inspect `/`, `/private`, and a nested path; confirm the response uses navigation findings rather than failing or hallucinating paths. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
