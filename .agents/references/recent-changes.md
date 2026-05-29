# Recent Changes

Open the workflow-specific rolling log that matches the current task.

## Policy
- Append an entry after each completed or paused implementation slice.
- Do not wait for unfinished work; completed changes must also be logged.
- Keep entries append-only and include rerun implications.

- Preprocessing work -> `recent-changes-preprocessing.md`
- Visual stimulation work -> `recent-changes-visual-stimulation.md`

## Compact Query Route

Before opening a workflow-specific append-only log, query it with:

```bash
python3 /Users/ddharmap/gitRepo/agenticWorkflow/scripts/query_recent_changes.py --repo <repo-name> --query <term> --limit 5
```

Open the full log only when the compact result points to an entry that needs detailed reading.
