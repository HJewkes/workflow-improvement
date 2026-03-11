#!/usr/bin/env python3
"""Workflow improvement CLI — handles all deterministic bookkeeping for the skill."""
import argparse, json, os, re, subprocess, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

BASE = Path.home() / ".claude" / "workflow-improvement"
OBSERVATIONS = BASE / "observations"
DESIGNS = BASE / "designs"
INSTANCES = BASE / "instances"
ARTIFACTS = BASE / "artifacts.jsonl"
DIGEST_SCRIPT = SCRIPT_DIR / "session-digest.py"
OBSERVER_TEMPLATE = SKILL_DIR / "references" / "observer.md"
DESIGNER_TEMPLATE = SKILL_DIR / "references" / "designer.md"
PROJECTS_DIR = Path.home() / ".claude" / "projects"

TEAM_NAME = "workflow-improvement"


def project_hash(cwd):
    return cwd.replace("/", "-")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_latest_log(phash):
    """Find the most recently modified session log for this project."""
    logs = list(PROJECTS_DIR.glob(f"{phash}/*.jsonl"))
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def render_template(template_path, variables):
    """Replace {VAR} placeholders in a template file. Fails on unfilled {ALLCAPS} placeholders."""
    text = template_path.read_text()
    for k, v in variables.items():
        text = text.replace(f"{{{k}}}", v)
    unfilled = re.findall(r'\{[A-Z][A-Z_]+\}', text)
    if unfilled:
        print(f"render_template: unfilled placeholders in {template_path}: {sorted(set(unfilled))}", file=sys.stderr)
        sys.exit(1)
    return text


def read_jsonl(path):
    if not path.exists():
        return []
    items = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return items


def write_jsonl(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(i) for i in items) + "\n" if items else "")


def append_jsonl(path, item):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(item) + "\n")


def next_obs_id(pending_file):
    """Compute next observation sequence number from existing pending observations."""
    existing = read_jsonl(pending_file)
    max_seq = 0
    for o in existing:
        parts = o.get("id", "").split("-")
        if len(parts) >= 4:
            try:
                max_seq = max(max_seq, int(parts[-1]))
            except ValueError:
                pass
    return max_seq + 1


def get_phash(args):
    """Resolve project hash from args or cwd."""
    return args.project_hash or project_hash(os.getcwd())


def get_state(phash):
    """Load instance state file."""
    state_file = INSTANCES / f"{phash}.json"
    if not state_file.exists():
        return {}
    return json.loads(state_file.read_text())


def save_state(phash, state):
    """Write instance state file."""
    state_file = INSTANCES / f"{phash}.json"
    state_file.write_text(json.dumps(state, indent=2))


def cmd_observer_init(args):
    """Full observer setup: init state, lock session log, output operating instructions."""
    cwd = os.getcwd()
    phash = project_hash(cwd)
    cli_path = str(SCRIPT_DIR / "workflow-improve.py")

    # Clean up stale instance
    state_file = INSTANCES / f"{phash}.json"
    if state_file.exists():
        state_file.unlink()

    # Ensure directories
    (OBSERVATIONS / phash).mkdir(parents=True, exist_ok=True)
    DESIGNS.mkdir(parents=True, exist_ok=True)
    INSTANCES.mkdir(parents=True, exist_ok=True)

    # Lock current session log
    session_log = find_latest_log(phash)
    session_log_path = str(session_log) if session_log else None

    # Write state file
    state = {
        "cron_id": None,
        "team_name": TEAM_NAME,
        "project": cwd,
        "project_hash": phash,
        "session_log": session_log_path,
        "started_at": now_iso(),
    }
    save_state(phash, state)

    # Render and output observer operating instructions
    prompt = render_template(OBSERVER_TEMPLATE, {
        "PROJECT_HASH": phash,
        "WORKFLOW_IMPROVE_PATH": cli_path,
        "TEAM_NAME": TEAM_NAME,
    })
    print(prompt)


def cmd_set_cron_id(args):
    """Update state file with cron ID after CronCreate."""
    phash = get_phash(args)
    state = get_state(phash)
    if not state:
        print("No active instance", file=sys.stderr)
        sys.exit(1)
    state["cron_id"] = args.cron_id
    save_state(phash, state)
    print(f"Updated cron_id to {args.cron_id}")


def cmd_shutdown(args):
    """Archive resolved observations, delete state. Returns cron_id for cleanup."""
    phash = get_phash(args)
    state = get_state(phash)
    cron_id = state.get("cron_id")

    # Archive observations with terminal statuses
    pending_file = OBSERVATIONS / phash / "pending.jsonl"
    archive_file = OBSERVATIONS / phash / "archive.jsonl"
    pending = read_jsonl(pending_file)
    archive_statuses = {"addressed", "dismissed", "duplicate"}
    to_archive = [o for o in pending if o.get("status") in archive_statuses]
    remaining = [o for o in pending if o.get("status") not in archive_statuses]

    if to_archive:
        for item in to_archive:
            append_jsonl(archive_file, item)
    write_jsonl(pending_file, remaining)

    state_file = INSTANCES / f"{phash}.json"
    if state_file.exists():
        state_file.unlink()

    print(json.dumps({
        "cron_id": cron_id,
        "team_name": TEAM_NAME,
        "archived_count": len(to_archive),
        "pending_count": len(remaining),
    }, indent=2))


def cmd_observe(args):
    """Run session-digest against locked session log, deduplicate against existing observations."""
    phash = get_phash(args)
    state = get_state(phash)
    cursor_file = OBSERVATIONS / phash / "cursor.json"

    # Read cursor (last-seen timestamp)
    cursor = {}
    if cursor_file.exists():
        try:
            cursor = json.loads(cursor_file.read_text())
        except json.JSONDecodeError:
            pass

    # Use locked session log from state, fall back to latest
    session_log = state.get("session_log")
    if session_log and Path(session_log).exists():
        cmd = [sys.executable, str(DIGEST_SCRIPT), session_log, "--json"]
    else:
        cmd = [sys.executable, str(DIGEST_SCRIPT), "--latest", f"--project={phash}", "--json"]

    if cursor.get("last_seen"):
        cmd.extend(["--after", cursor["last_seen"]])
    else:
        cmd.extend(["--since", str(args.since or 5)])

    r = subprocess.run(cmd, capture_output=True, text=True)

    if r.returncode != 0:
        print(json.dumps({"digest": {"errors": [], "retries": []}, "existing_titles": [], "digest_error": r.stderr.strip()}))
        sys.exit(0)

    try:
        digest = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(json.dumps({"digest": {"errors": [], "retries": []}, "existing_titles": [], "digest_error": "invalid JSON from session-digest"}))
        sys.exit(0)

    # Update cursor
    if digest.get("last_seen"):
        cursor["last_seen"] = digest["last_seen"]
        cursor_file.parent.mkdir(parents=True, exist_ok=True)
        cursor_file.write_text(json.dumps(cursor))

    pending_file = OBSERVATIONS / phash / "pending.jsonl"
    existing = read_jsonl(pending_file)
    existing_titles = {o.get("title", "").lower() for o in existing}

    print(json.dumps({
        "digest": digest,
        "existing_count": len(existing),
        "existing_titles": sorted(existing_titles),
    }, indent=2))


def cmd_record(args):
    """Record an observation. Deterministic fields auto-filled from instance state."""
    phash = get_phash(args)
    state = get_state(phash)

    date = datetime.now().strftime("%Y-%m-%d")
    pending_file = OBSERVATIONS / phash / "pending.jsonl"
    seq = next_obs_id(pending_file)

    obs = {
        "id": f"obs-{date}-{seq:03d}",
        "project": state.get("project", os.getcwd()),
        "date": date,
        "category": args.category,
        "impact": args.impact,
        "title": args.title,
        "description": args.description,
        "suggestion": args.suggestion,
        "status": "pending",
        "related": [],
        "design_id": None,
    }
    append_jsonl(pending_file, obs)
    print(json.dumps({"recorded": obs["id"], "observation": obs}))


def cmd_register_artifact(args):
    """Register an artifact produced by a designer agent."""
    phash = get_phash(args)
    state = get_state(phash)

    artifact = {
        "file": args.file,
        "type": args.type,
        "design_id": args.design_id,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "project": state.get("project", os.getcwd()),
        "auto_generated": True,
        "description": args.description,
    }
    append_jsonl(ARTIFACTS, artifact)
    print(json.dumps({"registered": args.file}))


def cmd_update_status(args):
    """Update an observation's status in pending.jsonl."""
    phash = get_phash(args)
    pending_file = OBSERVATIONS / phash / "pending.jsonl"
    items = read_jsonl(pending_file)
    found = False
    for item in items:
        if item.get("id") == args.obs_id:
            item["status"] = args.status
            if args.design_id:
                item["design_id"] = args.design_id
            found = True
            break
    if not found:
        print(f"Observation {args.obs_id} not found", file=sys.stderr)
        sys.exit(1)
    write_jsonl(pending_file, items)
    print(f"Updated {args.obs_id} -> {args.status}")


def cmd_status(args):
    """Quick status view."""
    phash = get_phash(args)
    state = get_state(phash)
    pending_file = OBSERVATIONS / phash / "pending.jsonl"
    archive_file = OBSERVATIONS / phash / "archive.jsonl"

    print(json.dumps({
        "active": bool(state),
        "instance": state or None,
        "pending_observations": len(read_jsonl(pending_file)),
        "archived_observations": len(read_jsonl(archive_file)),
        "designs": len(list(DESIGNS.glob("*.md"))) if DESIGNS.exists() else 0,
        "artifacts": len(read_jsonl(ARTIFACTS)),
    }, indent=2))


def cmd_report(args):
    """Generate a clean report of all improvements made."""
    phash = get_phash(args)
    pending_file = OBSERVATIONS / phash / "pending.jsonl"
    archive_file = OBSERVATIONS / phash / "archive.jsonl"

    pending = read_jsonl(pending_file)
    archived = read_jsonl(archive_file)
    all_obs = pending + archived
    artifacts = read_jsonl(ARTIFACTS)

    # Load design docs
    designs = []
    if DESIGNS.exists():
        for f in sorted(DESIGNS.glob("*.md")):
            designs.append({"file": f.name, "path": str(f)})

    # Group observations by status
    by_status = {}
    for o in all_obs:
        s = o.get("status", "unknown")
        by_status.setdefault(s, []).append(o)

    # Build report
    lines = ["# Workflow Improvement Report", ""]

    addressed = by_status.get("addressed", [])
    dismissed = by_status.get("dismissed", [])
    still_pending = by_status.get("pending", [])
    lines.append(f"**{len(all_obs)} observations** total: "
                 f"{len(addressed)} addressed, {len(dismissed)} dismissed, "
                 f"{len(still_pending)} pending")
    lines.append(f"**{len(designs)} designs** created, **{len(artifacts)} artifacts** produced")
    lines.append("")

    if addressed:
        lines.append("## Improvements Implemented")
        lines.append("")
        for o in addressed:
            design = o.get("design_id", "")
            lines.append(f"- **{o['title']}** ({o['category']}, {o['date']})")
            lines.append(f"  {o['description']}")
            if design:
                lines.append(f"  Design: `{design}`")
            lines.append("")

    if artifacts:
        lines.append("## Artifacts Created")
        lines.append("")
        for a in artifacts:
            lines.append(f"- `{a['file']}` — {a['description']} (design: `{a.get('design_id', '?')}`)")
        lines.append("")

    if still_pending:
        lines.append("## Pending Observations")
        lines.append("")
        for o in still_pending:
            lines.append(f"- [{o['impact']}] **{o['title']}** ({o['category']})")
            if o.get("suggestion"):
                lines.append(f"  Suggestion: {o['suggestion']}")
        lines.append("")

    if dismissed:
        lines.append("## Dismissed")
        lines.append("")
        for o in dismissed:
            lines.append(f"- ~~{o['title']}~~ ({o['category']}, {o['impact']})")
        lines.append("")

    print("\n".join(lines))


def cmd_render_designer(args):
    """Render designer prompt. Looks up observation by ID from pending.jsonl."""
    phash = get_phash(args)
    cwd = args.cwd or os.getcwd()
    cli_path = str(SCRIPT_DIR / "workflow-improve.py")

    pending_file = OBSERVATIONS / phash / "pending.jsonl"
    obs = None
    for item in read_jsonl(pending_file):
        if item.get("id") == args.observation_id:
            obs = item
            break
    if not obs:
        print(f"Observation {args.observation_id} not found", file=sys.stderr)
        sys.exit(1)

    prompt = render_template(DESIGNER_TEMPLATE, {
        "CWD": cwd,
        "DATE": datetime.now().strftime("%Y-%m-%d"),
        "OBSERVATION_JSON": json.dumps(obs),
        "OBSERVATION_ID": args.observation_id,
        "DESIGNS_DIR": str(DESIGNS),
        "SLUG": args.slug,
        "WORKFLOW_IMPROVE_PATH": cli_path,
        "PROJECT_HASH": phash,
        "TEAM_NAME": TEAM_NAME,
    })
    print(prompt)


def main():
    ap = argparse.ArgumentParser(description="Workflow improvement CLI")
    ap.add_argument("--project-hash", help="Override project hash (default: derived from cwd)")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("observer-init")

    p = sub.add_parser("set-cron-id")
    p.add_argument("cron_id")

    sub.add_parser("shutdown")

    p = sub.add_parser("observe")
    p.add_argument("--since", type=int, help="Minutes to look back (default 5)")

    p = sub.add_parser("record")
    p.add_argument("--category", required=True)
    p.add_argument("--impact", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--suggestion", default=None)

    p = sub.add_parser("register-artifact")
    p.add_argument("--file", required=True)
    p.add_argument("--type", required=True)
    p.add_argument("--design-id", required=True)
    p.add_argument("--description", required=True)

    p = sub.add_parser("update-status")
    p.add_argument("obs_id")
    p.add_argument("status")
    p.add_argument("--design-id")

    sub.add_parser("status")
    sub.add_parser("report")

    p = sub.add_parser("render-designer")
    p.add_argument("--observation-id", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--cwd")

    args = ap.parse_args()
    {
        "observer-init": cmd_observer_init,
        "set-cron-id": cmd_set_cron_id,
        "shutdown": cmd_shutdown,
        "observe": cmd_observe,
        "record": cmd_record,
        "register-artifact": cmd_register_artifact,
        "update-status": cmd_update_status,
        "status": cmd_status,
        "report": cmd_report,
        "render-designer": cmd_render_designer,
    }[args.command](args)


if __name__ == "__main__":
    main()
