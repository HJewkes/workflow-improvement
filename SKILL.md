---
name: workflow-improvement
description: Start background observation that watches your session for friction and implements improvements. Use when you say "start workflow improvement", "/workflow-improvement", or "watch for friction".
---

# Workflow Improvement

Cron-based observation loop that periodically scans your session for friction patterns and autonomously spawns designer agents to implement improvements. Fire-and-forget — once activated, the coordinator can move on.

## Activation

Trigger phrases: `/workflow-improvement`, `start workflow improvement`, `watch for friction`

To stop: say `stop workflow improvement`.

## How It Works

1. **Observer cron** fires every 3 minutes. It tails session logs for errors/retries, classifies friction, records observations, and autonomously spawns designer agents for high-impact findings.
2. **Designer agents** are spawned by the observer (not the coordinator). Each designs and implements one minimal improvement, then exits.

The coordinator's only job is setup and teardown.

## CLI Tool

All deterministic bookkeeping is handled by `scripts/workflow-improve.py`. The `--project-hash` flag is top-level and optional (defaults to cwd-derived hash).

```
workflow-improve activate                    # Setup: render prompt, write state, return cli_path
workflow-improve set-cron-id ID              # Save cron ID after CronCreate
workflow-improve shutdown                    # Archive, list results, clean up
workflow-improve observe                     # Session-digest + dedup
workflow-improve record --category C --impact I --title T --description D  # Record observation
workflow-improve register-artifact --file F --type T --design-id D --description D  # Register artifact
workflow-improve update-status ID STATUS     # Update observation status
workflow-improve render-designer --observation-id ID --slug SLUG  # Render designer prompt
workflow-improve status                      # Quick status view
```

## Setup Procedure

When invoked, execute these 4 steps then move on:

### Step 1: Activate

```bash
python3 <path-to-skill>/scripts/workflow-improve.py activate
```

> **How to find `<path-to-skill>`**: Search for `workflow-improve.py` under `~/.claude/skills/` or the skill's install location. The activate output includes `cli_path` — use that for all subsequent calls.

This outputs JSON with:
- `cli_path` — full path to the CLI script (use for step 3)
- `observer_prompt` — fully rendered observer prompt
- `project_hash`, `state_file` — instance metadata
- `stale_instance` — if present, CronDelete its `cron_id` first

### Step 2: Create observer cron

Use CronCreate:
- **Expression**: `*/3 * * * *` (every 3 minutes)
- **Prompt**: The `observer_prompt` value from Step 1
- **Recurring**: true

### Step 3: Save cron ID

```bash
python3 <cli_path> set-cron-id <CRON_TASK_ID>
```

### Step 4: Confirm to user

Tell the user:
- Workflow improvement is running (observer cron every 3 min)
- It will autonomously detect friction and implement fixes
- Say "stop workflow improvement" to shut down

**That's it. Do not monitor cron output or manage designer dispatch — the observer handles everything autonomously.**

## Shutdown Procedure

When the user says "stop workflow improvement":

### Step 1: Get shutdown data

```bash
python3 <cli_path> shutdown
```

Returns JSON with `cron_id`, `archived_count`, `pending_count`, `session_observations`, `designs`, `artifacts`.

### Step 2: CronDelete

Use CronDelete with the `cron_id` from shutdown output.

### Step 3: Summarize to user

Summarize: observations recorded, designs created, improvements implemented.

## Storage

All runtime data lives at `~/.claude/workflow-improvement/`:

| What | Path | Format |
|------|------|--------|
| Observations | `observations/{project}/pending.jsonl` | JSONL |
| Archive | `observations/{project}/archive.jsonl` | JSONL |
| Designs | `designs/design-{date}-{slug}.md` | Markdown + YAML frontmatter |
| Artifacts | `artifacts.jsonl` | JSONL |
| Instances | `instances/{project}.json` | JSON (one per active instance) |
