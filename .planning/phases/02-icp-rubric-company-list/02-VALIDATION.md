---
phase: 2
slug: icp-rubric-company-list
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python inline scripts (existing pattern from Phase 1) |
| **Config file** | none — scripts run directly |
| **Quick run command** | `python scripts/test_icp_scorer.py` |
| **Full suite command** | `python scripts/test_icp_scorer.py && python -c "from src.pipeline.companies import get_all_companies; print(len(get_all_companies()), 'companies loaded')"` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python scripts/test_icp_scorer.py`
- **After every plan wave:** Run full suite command above
- **Before `/gsd:verify-work`:** Full suite must be green (19 tests passing, 20 companies loaded)
- **Max feedback latency:** ~5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 2-01-01 | 02-01 | 1 | INTEL-01,02,03 | unit | `python scripts/test_icp_scorer.py` | ⬜ pending |
| 2-01-02 | 02-01 | 1 | INTEL-01,02 | unit | `python scripts/test_icp_scorer.py` (19 tests) | ⬜ pending |
| 2-02-01 | 02-02 | 1 | INTEL-01,02,03 | unit | `python -c "from src.pipeline.companies import get_all_companies; c=get_all_companies(); assert len(c)==20"` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements.*

- `scripts/test_icp_scorer.py` already exists with 17 passing tests
- No new test framework needed

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| known_industry_hint strings produce correct ICP tier when fed to score_industry_fit() | INTEL-01 | Spot-check rubric alignment | Run `python -c "from src.pipeline.icp_scorer import score_industry_fit; print(score_industry_fit('petrochemical polymer resin manufacturing').score)"` — expect 4 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
