# Sprint 007a — Post-Demo Fixes (v0.7.0 feedback)

**Status**: Done
**Goal**: Address blocking findings from the v0.7.0 demo. Primary fix: `--json`/`--verbose`/`--quiet` flags not recognized when placed after subcommands (`revolver llm list --json` → "No such option"). Secondary: any additional findings from demo feedback.
**Demo**: `revolver llm list --json` returns valid JSON; `revolver doctor --json` returns `{checks, status, errors, warnings}`; all 7 tested commands accept `--json` at any position.

---

## Source

- Demo feedback: `feedback.md` of the TSP demo v0.7.0 (private demo repository)
- Session: 035 (2026-03-20)

---

## Findings from Demo v0.7.0

| ID | Severity | Description | Status |
|---|---|---|---|
| F1 | BLOQUANT | `--json` not recognized on any subcommand (0/7 tested) | Fix in PR #81 |
| F2 | INVALIDE | `doctor` shows wrong version — caused by stale install in demo env | N/A |

---

## Tasks

| ID | Task | PR | Status |
|---|---|---|---|
| S7a-01 | Fix `--json`/`--verbose`/`--quiet` flag propagation to subcommands | #81 | Done |
| S7a-02 | Validate fix against all 7 demo-tested commands | #81 | Done (2 integration tests added) |
| S7a-03 | Release v0.7.1 with fix | v0.7.1 | Done |

---

## Technical Approach (S7a-01)

**Root cause**: Click groups parse their own options before delegating to subcommands. `--json` on the root callback only works with `revolver --json llm list`, not `revolver llm list --json`.

**Fix**: Custom `GlobalOptionGroup` and `GlobalOptionCommand` Click subclasses in `src/revolver/cli/_global_options.py` that intercept `--json`/`--verbose`/`--quiet` at parse time, before Click's normal option processing. Applied to root app and all 8 sub-Typer groups via `cls=` parameter.

**Advantages over per-command approach**:
- Single file change + `__init__.py` wiring (vs. modifying 9 modules and 20+ functions)
- Zero per-command boilerplate
- Both syntaxes work: `revolver --json llm list` AND `revolver llm list --json`

---

## Parallelization

Sequential — single fix PR, then release.
