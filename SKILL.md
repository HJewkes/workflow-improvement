---
name: workflow-improvement
description: Start background observation that watches your session for friction and implements improvements. Use when you say "start workflow improvement", "/workflow-improvement", or "watch for friction".
---

# Workflow Improvement

Cron-based observation loop that periodically scans your session for friction patterns and spawns one-shot designer agents to implement improvements.

## Activation

Trigger phrases: `/workflow-improvement`, `start workflow improvement`, `watch for friction`

To stop: say `stop workflow improvement`.

## What It Does

1. **Observer cron** — fires every 3 minutes, runs `observe` to extract friction from session logs, classifies findings, records them via `record`. If high-impact friction is found, recommends designer dispatch.
2. **Designer subagent** — spawned on-demand for high-impact friction. Designs and implements a minimal improvement, then exits.

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

When invoked, execute these steps:

### Step 1: Activate

```bash
python3 <path-to-skill>/scripts/workflow-improve.py activate
```

> **How to find `<path-to-skill>`**: Search for `workflow-improve.py` under `~/.claude/skills/` or the skill's install location. The activate output includes `cli_path` — use that for all subsequent calls.

This outputs JSON with:
- `cli_path` — full path to the CLI script (use this for all subsequent calls)
- `observer_prompt` — fully rendered observer prompt (all placeholders filled)
- `project_hash`, `state_file` — instance metadata
- `stale_instance` — if present, a previous instance was cleaned up (CronDelete its `cron_id` first)

### Step 2: Create observer cron

Use CronCreate:
- **Expression**: `*/3 * * * *` (every 3 minutes)
- **Prompt**: The `observer_prompt` value from Step 1
- **Recurring**: true

### Step 3: Save cron ID

```bash
python3 <cli_path> set-cron-id <CRON_TASK_ID>
```

### Step 4: Set up designer dispatch

The observer's output is checked after each cron fire. If the output contains
`DISPATCH_DESIGNER: true`, render the designer prompt:

```bash
python3 <cli_path> render-designer \
    --observation-id '<from observer output>' \
    --slug '<derived from title>'
```

Spawn as a background `general-purpose` agent with the rendered prompt.

### Step 5: Confirm to user

Tell the user:
- Workflow improvement observer is running (cron every 3 min)
- Session logs are being scanned for friction patterns
- Designer agents will be spawned for high-impact findings
- Say "stop workflow improvement" to shut down

## Shutdown Procedure

When the user says "stop workflow improvement":

### Step 1: Get shutdown data

```bash
python3 <cli_path> shutdown
```

This outputs JSON with:
- `cron_id` — use for CronDelete
- `archived_count`, `pending_count` — observation counts
- `session_observations` — this session's observations
- `designs` — design docs created
- `artifacts` — registered artifacts

### Step 2: CronDelete

Use CronDelete with the `cron_id` from shutdown output.

### Step 3: Summarize to user

Using the shutdown JSON, summarize:
- Number of observations recorded (and how many archived)
- Any designs created and improvements implemented

## Storage

All runtime data lives at `~/.claude/workflow-improvement/`:

| What | Path | Format |
|------|------|--------|
| Observations | `observations/{project}/pending.jsonl` | JSONL |
| Archive | `observations/{project}/archive.jsonl` | JSONL |
| Designs | `designs/design-{date}-{slug}.md` | Markdown + YAML frontmatter |
| Artifacts | `artifacts.jsonl` | JSONL |
| Instances | `instances/{project}.json` | JSON (one per active instance) |

## Notes

- Observer is stateless — each cron fire reads files, writes observations, exits
- Designer is one-shot — spawned per high-impact observation, implements one fix, exits
- All deterministic bookkeeping (file I/O, dedup, archival, ID generation) is in the CLI
- Agents focus only on judgment: classifying friction, assessing impact, designing solutions
