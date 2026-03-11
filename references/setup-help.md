# Setup Help: Finding the Skill Directory

If the default CLI path in SKILL.md doesn't work, follow these steps to locate and fix it.

## 1. Find the skill

```bash
find ~/.claude/skills -name "workflow-improve.py" 2>/dev/null
find .claude/skills -name "workflow-improve.py" 2>/dev/null
```

The script lives at `<skill-dir>/scripts/workflow-improve.py`. The `<skill-dir>` is whichever directory contains both `scripts/` and `references/` alongside `SKILL.md`.

## 2. Verify it works

```bash
python3 <found-path>/scripts/workflow-improve.py --help
```

## 3. Update SKILL.md

Edit the `python3` command in Step 1 of the Setup Procedure to use the correct absolute path. This is a one-time fix — once updated, all subsequent activations will work.

## Common install locations

| Install method | Location |
|---|---|
| Symlink (default) | `~/.claude/skills/workflow-improvement/` |
| npx skills add | `~/.claude/skills/workflow-improvement/` |
| Project-local | `.claude/skills/workflow-improvement/` (relative to project root) |
| Git clone | wherever you cloned it |
