---
phase: "01"
plan: "02"
subsystem: environment
tags: [dependencies, gitignore, reproducibility]
dependency_graph:
  requires: [01-01]
  provides: [requirements.txt, .gitignore]
  affects: [all-phases]
tech_stack:
  added: []
  patterns: [pip freeze pinning, gitignore exclusion]
key_files:
  created:
    - requirements.txt
    - .gitignore
  modified:
    - .planning/STATE.md
decisions:
  - "Used full pip freeze output (217 packages) rather than a curated minimal list — ensures exact reproducibility with the test environment"
  - ".gitignore created fresh (no prior file existed); excludes data/raw/, data/processed/, outputs/, logs/, .env*, venv, __pycache__, IDE and OS artifacts"
metrics:
  duration: "~3 minutes"
  completed: "2026-04-15"
  tasks: 2
  files: 2
---

# Phase 1 Plan 02: Requirements File and Gitignore Summary

## One-liner

Full pip freeze to requirements.txt (217 packages, all key deps confirmed) plus .gitignore excluding data/raw/, outputs/, logs/, secrets, and caches.

## What Was Built

### Task 1: requirements.txt

Ran `pip freeze` against the project Python environment and wrote the output to `requirements.txt` at the project root. The file contains 217 pinned packages.

All 11 key packages verified present:

| Package | Version |
|---------|---------|
| pydantic | 2.11.7 |
| fastapi | 0.116.1 |
| RapidFuzz | 3.14.5 |
| geopy | 2.4.1 |
| pandas | 2.3.1 |
| tqdm | 4.67.1 |
| openpyxl | 3.1.5 |
| uvicorn | 0.35.0 |
| tenacity | 9.1.4 |
| requests | 2.32.3 |
| httpx | 0.28.1 |

Note: `pip check` surfaced 4 warnings about `flax` requiring `orbax-checkpoint`, `orbax-export`, `tensorstore` (not installed), and an optax version mismatch. These are unrelated to this pipeline — flax is an ML framework not used by any pipeline module.

### Task 2: .gitignore

Created `.gitignore` at project root. No prior file existed.

Sections included:
- `data/raw/` and `data/processed/` — raw/intermediate pipeline data
- `outputs/` — final deliverable CSVs/XLSXs
- `logs/` — pipeline execution logs
- `.env`, `.env.*`, `!.env.example` — secrets
- Python cache files (`__pycache__/`, `*.pyc`, `*.pyo`, `*.pyd`, `*.egg-info/`, `dist/`, `build/`)
- Virtual environments (`venv/`, `.venv/`, `env/`, `.env/`)
- IDE files (`.vscode/`, `.idea/`, `*.swp`, `*.swo`)
- OS files (`.DS_Store`, `Thumbs.db`)
- Jupyter artifacts (`.ipynb_checkpoints/`, `*.ipynb`)

## Verification Results

### requirements.txt verification

```
fastapi==0.116.1      FOUND
geopy==2.4.1          FOUND
httpx==0.28.1         FOUND
openpyxl==3.1.5       FOUND
pandas==2.3.1         FOUND
pydantic==2.11.7      FOUND
RapidFuzz==3.14.5     FOUND
requests==2.32.3      FOUND
tenacity==9.1.4       FOUND
tqdm==4.67.1          FOUND
uvicorn==0.35.0       FOUND
```

All 11 key packages: PASS

### .gitignore verification

```
$ git check-ignore -v data/raw/ outputs/ logs/
.gitignore:2:data/raw/    data/raw/
.gitignore:6:outputs/     outputs/
.gitignore:9:logs/        logs/
```

All three exclusions active: PASS

## Commits

| Hash | Message |
|------|---------|
| 46f4f4d | chore(01-02): add requirements.txt and .gitignore |

## Deviations from Plan

None — plan executed exactly as written. No packages were missing from pip freeze; no install step was needed. `.gitignore` did not exist prior, so the full content was written directly (no append logic required).

## Known Stubs

None.

## Self-Check: PASSED

- `C:\Users\dhruv\TractianCase-DhruvGupta\requirements.txt` — exists (217 lines)
- `C:\Users\dhruv\TractianCase-DhruvGupta\.gitignore` — exists
- Commit `46f4f4d` — confirmed in git log
- `git check-ignore` matched all three target paths
