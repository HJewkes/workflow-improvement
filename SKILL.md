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

1. **Observer cron** — fires every 3 minutes, runs `workflow-improve observe` to extract friction from session logs, asks the LLM to classify findings, then records them via `workflow-improve record`. If high-impact friction is found, recommends designer dispatch.
2. **Designer subagent** — spawned on-demand when high-impact friction is detected. Designs and implements a minimal improvement, then exits.

## CLI Tool

All deterministic bookkeeping is handled by `scripts/workflow-improve.py`:

```
workflow-improve activate          # Setup: env discovery, stale cleanup, render prompt, write state
workflow-improve set-cron-id ID    # Save cron ID to state file after CronCreate
workflow-improve shutdown          # Archive observations, list results, clean up state
workflow-improve observe           # Run session-digest + deduplicate against existing
workflow-improve record --category C --impact I --title T --description D  # Record observation (id/session/date auto-filled)
workflow-improve register-artifact 'JSON'  # Append to artifacts.jsonl
workflow-improve update-status ID STATUS   # Update observation status
workflow-improve render-designer --observation-json 'JSON' --observation-id ID --slug SLUG
workflow-improve status            # Quick status view
```

## Agent Prompts

| Agent | Reference |
|-------|-----------|
| observer | [references/observer.md](references/observer.md) |
| designer | [references/designer.md](references/designer.md) |

## Setup Procedure

When invoked, execute these steps:

### Step 1: Activate

```bash
python3 <skill-dir>/scripts/workflow-improve.py activate
```

This outputs JSON with:
- `observer_prompt` — fully rendered observer prompt (all placeholders filled)
- `project_hash`, `session_id`, `state_file` — instance metadata
- `stale_instance` — if present, a previous instance was cleaned up (report the `cron_id` from it to CronDelete)

If `stale_instance` is present in the output, CronDelete the old `cron_id` first.

### Step 2: Create observer cron

Use CronCreate:
- **Expression**: `*/3 * * * *` (every 3 minutes)
- **Prompt**: The `observer_prompt` value from Step 1
- **Recurring**: true

### Step 3: Save cron ID

```bash
python3 <skill-dir>/scripts/workflow-improve.py set-cron-id <CRON_TASK_ID>
```

### Step 4: Set up designer dispatch

The observer's output is checked after each cron fire. If the output contains
`DISPATCH_DESIGNER: true`, render the designer prompt:

```bash
python3 <skill-dir>/scripts/workflow-improve.py render-designer \
    --observation-json '<from observer output>' \
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
python3 <skill-dir>/scripts/workflow-improve.py shutdown
```

This outputs JSON with:
- `cron_id` — use this for CronDelete
- `archived_count` — observations moved to archive
- `session_observations` — this session's pending observations
- `designs` — list of design docs created
- `artifacts` — list of registered artifacts

### Step 2: CronDelete

Use CronDelete with the `cron_id` from shutdown output.

### Step 3: Summarize to user

Using the shutdown JSON, summarize:
- Number of observations recorded (and how many archived)
- Any designs created and improvements implemented
- This is the only step that needs LLM judgment

## Storage

| What | Where | Format |
|------|-------|--------|
| Observations | `~/.claude/workflow-improvement/observations/{project}/pending.jsonl` | JSONL |
| Archive | `~/.claude/workflow-improvement/observations/{project}/archive.jsonl` | JSONL |
| Designs | `~/.claude/workflow-improvement/designs/design-{date}-{slug}.md` | Markdown + YAML frontmatter |
| Artifacts | `~/.claude/workflow-improvement/artifacts.jsonl` | JSONL |
| Instances | `~/.claude/workflow-improvement/instances/{project}.json` | JSON (one per active instance) |

## Notes

- Observer is stateless — each cron fire reads files, writes observations, exits
- Designer is one-shot — spawned per high-impact observation, implements one fix, exits
- All deterministic bookkeeping (file I/O, dedup, archival) is in the CLI, not the agent prompts
- Agents focus only on judgment: classifying friction, assessing impact, designing solutions
- `session-digest` handles efficient log tailing (never reads full JSONL files)
