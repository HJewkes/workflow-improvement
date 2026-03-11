# workflow-improvement

A Claude Code skill that watches your session for friction patterns and automatically implements improvements.

## Install

```bash
npx @anthropic-ai/skills add HJewkes/workflow-improvement
```

## Usage

In any Claude Code session, say:

- `/workflow-improvement`
- `start workflow improvement`
- `watch for friction`

To stop: `stop workflow improvement`

## How It Works

1. **Observer cron** fires every 3 minutes, tailing your session logs for errors, retries, and repeated tool calls
2. Each friction signal is classified by impact and recorded as a structured observation
3. **Designer agents** are spawned on-demand for high-impact findings — they design and implement minimal fixes (Makefile targets, scripts, CLAUDE.md updates)
4. All bookkeeping (dedup, archival, state) is handled by a CLI tool, so agents focus purely on judgment

## Architecture

```
SKILL.md              # Skill entry point
references/
  observer.md         # Cron-fired observer agent prompt
  designer.md         # One-shot designer agent prompt
scripts/
  workflow-improve.py  # CLI for all deterministic bookkeeping
  session-digest.py    # Session log parser
  render_template.sh   # Bash template renderer
```

Runtime data is stored at `~/.claude/workflow-improvement/` (observations, designs, artifacts, instance state).

## License

MIT
