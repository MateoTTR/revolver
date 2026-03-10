---
name: session-close
description: Close the current Revolver session with a report, cost tracker update, and backlog update
disable-model-invocation: true
argument-hint: "<duration> <tokens>"
---

Close the current session. The user provides session duration and token count as arguments: $ARGUMENTS

Follow these steps exactly:

## 1. Determine session number

Read `docs/sessions/cost-tracker.md` to find the last session number. The new session is N+1.
Read the latest session report in `docs/sessions/` for the previous session's context.

## 2. Gather session context

Review all files you created or modified during this session. Use `git status` and `git diff` to identify changes.
Read `docs/tasks/backlog.md` to identify which tasks were completed.

## 3. Create session report

Create `docs/sessions/YYYY-MM-DD-session-NNN.md` with this structure:

```markdown
# Session NNN — YYYY-MM-DD

**Phase**: (current phase)
**Duration**: (from $ARGUMENTS or ask user)
**Tokens**: (from $ARGUMENTS or ask user)

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

Edit `docs/sessions/cost-tracker.md`:
- Add a new row to the session log table
- Recalculate cumulative totals (total sessions, total duration, averages)

## 5. Update backlog

Verify `docs/tasks/backlog.md` — ensure all completed tasks are marked `[x]` with the session number.

## 6. Confirm with user

Show a summary of what was created/updated and ask for validation before committing.
Do NOT commit automatically — wait for explicit user instruction.
