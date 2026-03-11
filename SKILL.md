---
name: workflow-improvement
description: Start background observation that watches your session for friction and implements improvements. Use when you say "start workflow improvement", "/workflow-improvement", or "watch for friction".
---

# Workflow Improvement

Team-based observation system that watches your session for friction patterns and autonomously implements improvements. Uses Claude Code agent teams — the coordinator sets up the team, then moves on.

## Activation

Trigger phrases: `/workflow-improvement`, `start workflow improvement`, `watch for friction`

To stop: say `stop workflow improvement`.

## How It Works

1. Coordinator creates a `workflow-improvement` team and spawns an **Observer** agent
2. Coordinator creates a cron that wakes the observer every 3 minutes via SendMessage
3. Observer accumulates context across checks — spots recurring patterns, escalates persistent issues
4. Observer spawns **Designer** agents into the team for high-impact findings
5. Designers implement fixes, report back to observer, and exit

The coordinator's only job is setup and teardown. The observer manages everything autonomously.

## CLI Tool

`scripts/workflow-improve.py` — all deterministic bookkeeping. `--project-hash` is top-level, optional.

```
workflow-improve activate                    # Setup: render prompt, write state, return cli_path
workflow-improve set-cron-id ID              # Save cron ID after CronCreate
workflow-improve shutdown                    # Archive, clean up, return cron_id
workflow-improve observe                     # Session-digest + dedup
workflow-improve record --category C --impact I --title T --description D
workflow-improve register-artifact --file F --type T --design-id D --description D
workflow-improve update-status ID STATUS
workflow-improve render-designer --observation-id ID --slug SLUG
workflow-improve status                      # Quick status view
workflow-improve report                      # Full improvement report (markdown)
```

## Setup Procedure

### Step 1: Activate

```bash
python3 <path-to-skill>/scripts/workflow-improve.py activate
```

> Search for `workflow-improve.py` under `~/.claude/skills/` or the skill's install location. The output includes `cli_path` — use that for all subsequent calls.

Returns: `cli_path`, `project_hash`, `team_name`, `observer_prompt`, `state_file`, and optionally `stale_instance`.

If `stale_instance` is present, CronDelete its `cron_id` first.

### Step 2: Create team

Use TeamCreate:
- **team_name**: the `team_name` from activate output (`workflow-improvement`)
- **description**: "Watches session for friction and implements improvements"

### Step 3: Spawn observer

Use the Agent tool to spawn the observer:
- **team_name**: `workflow-improvement`
- **name**: `observer`
- **subagent_type**: `general-purpose`
- **run_in_background**: true
- **prompt**: the `observer_prompt` from Step 1

### Step 4: Create wake-up cron

Use CronCreate to periodically wake the observer:
- **Expression**: `*/3 * * * *`
- **Recurring**: true
- **Prompt**: `"Send a message to the observer in the workflow-improvement team telling it to run its periodic observation check."`

Save the cron ID:
```bash
python3 <cli_path> set-cron-id <CRON_TASK_ID>
```

### Step 5: Confirm to user

Tell the user:
- Workflow improvement team is active with an observer agent
- Checks run every 3 minutes, designer agents spawn for high-impact findings
- Say "stop workflow improvement" to shut down and see results

**Done. Do not monitor the team — the observer manages everything.**

## Shutdown Procedure

### Step 1: Generate report

```bash
python3 <cli_path> report
```

This outputs a markdown summary of all observations, improvements, and artifacts.

### Step 2: Shut down observer

Send a shutdown request to the observer via SendMessage (`type: "shutdown_request"`, `recipient: "observer"`).

### Step 3: Clean up state

```bash
python3 <cli_path> shutdown
```

Returns `cron_id` and `team_name` for cleanup.

### Step 4: Clean up resources

1. CronDelete with the `cron_id` from shutdown output
2. TeamDelete to remove the team

### Step 5: Present report

Show the user the report from Step 1.

## Storage

All runtime data lives at `~/.claude/workflow-improvement/`:

| What | Path | Format |
|------|------|--------|
| Observations | `observations/{project}/pending.jsonl` | JSONL |
| Archive | `observations/{project}/archive.jsonl` | JSONL |
| Designs | `designs/design-{date}-{slug}.md` | Markdown + YAML frontmatter |
| Artifacts | `artifacts.jsonl` | JSONL |
| Instances | `instances/{project}.json` | JSON (one per active instance) |
