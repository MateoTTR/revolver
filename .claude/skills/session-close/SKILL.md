---
name: session-close
description: Close the current Revolver session with a report and a cost row in the maintainer's private journal (configured in CLAUDE.local.md), plus a backlog update
disable-model-invocation: true
argument-hint: "<duration>"
---

Close the current session. The user provides session duration as argument: $ARGUMENTS

**Note**: Token counts are NOT tracked for this project. Only session durations are recorded.

**Journal location**: the session reports and the cost tracker live in the maintainer's private journal, outside the repository. Its path is given in the git-ignored `CLAUDE.local.md`. Nothing is written under `docs/sessions/` (that directory holds only a README pointer). If `CLAUDE.local.md` does not configure a journal, skip steps 1, 3 and 4 and only perform the backlog update (step 5).

Follow these steps exactly:

## 1. Recover the previous session's context

Read the latest entry under `<journal>/sessions/` for the previous session's context. Session files are named by date and topic (`YYYY-MM-DD-<short-topic>.md`); there is no global session counter.

## 2. Gather session context

Review all files you created or modified during this session. Use `git status` and `git diff` to identify changes.
Read `docs/tasks/backlog.md` to identify which tasks were completed.

## 3. Create session report

Create `<journal>/sessions/YYYY-MM-DD-<short-topic>.md` with this structure:

```markdown
# Session YYYY-MM-DD — <short topic>

**Phase**: (current phase)
**Duration**: (from $ARGUMENTS or ask user)

---

## Objectives

- (what was planned for this session)

## Work Completed

### (group by topic)
- (describe what was done, with file references)

## Files Created/Modified

### Created
- (list new files)

### Modified
- (list modified files with summary of changes)

## Next Steps

- [ ] (upcoming tasks from backlog)
```

## 4. Update cost tracker

Edit `<journal>/cost-tracker.md`:
- Add a new row to the session log table
- Recalculate cumulative totals (total sessions, total duration, averages)

## 5. Update backlog

Verify `docs/tasks/backlog.md` — ensure all completed tasks are marked `[x]` with the session date. (Until the Sprint 019 freeze; afterwards update the GitHub issues/milestone instead.)

## 6. Confirm with user

Show a summary of what was created/updated and ask for validation before committing.

## 7. Commit and push

After user validation, commit the repository changes (backlog) and push to remote. The journal files are outside the repository and are never committed.
Commit message format: `Close session YYYY-MM-DD: <brief summary>` (the same format applies when no journal is configured and only the backlog changed)
Do NOT commit or push without explicit user validation from step 6.
