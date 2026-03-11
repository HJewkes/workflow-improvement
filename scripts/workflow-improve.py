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


def project_hash(cwd):
    return cwd.replace("/", "-")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


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


def cmd_activate(args):
    """Setup: discover env, check stale, mkdir, render prompt, write state."""
    cwd = args.cwd or os.getcwd()
    phash = project_hash(cwd)
    session_id = str(uuid.uuid4())
    cli_path = str(SCRIPT_DIR / "workflow-improve.py")

    # Check for stale instance
    state_file = INSTANCES / f"{phash}.json"
    stale_info = None
    if state_file.exists():
        stale = json.loads(state_file.read_text())
        stale_info = {"cron_id": stale.get("cron_id"), "started_at": stale.get("started_at")}
        state_file.unlink()

    # Ensure directories
    (OBSERVATIONS / phash).mkdir(parents=True, exist_ok=True)
    DESIGNS.mkdir(parents=True, exist_ok=True)
    INSTANCES.mkdir(parents=True, exist_ok=True)

    # Render observer prompt
    observer_prompt = render_template(OBSERVER_TEMPLATE, {
        "PROJECT_HASH": phash,
        "WORKFLOW_IMPROVE_PATH": cli_path,
    })

    # Write state file (cron_id filled later by agent after CronCreate)
    state = {
        "cron_id": None,
        "session_id": session_id,
        "project": cwd,
        "project_hash": phash,
        "started_at": now_iso(),
    }
    state_file.write_text(json.dumps(state, indent=2))

    result = {
        "cli_path": cli_path,
        "project_hash": phash,
        "state_file": str(state_file),
        "observer_prompt": observer_prompt,
    }
    if stale_info:
        result["stale_instance"] = stale_info
    print(json.dumps(result, indent=2))


def cmd_set_cron_id(args):
    """Update state file with cron ID after CronCreate."""
    phash = get_phash(args)
    state_file = INSTANCES / f"{phash}.json"
    if not state_file.exists():
        print("No active instance", file=sys.stderr)
        sys.exit(1)
    state = json.loads(state_file.read_text())
    state["cron_id"] = args.cron_id
    state_file.write_text(json.dumps(state, indent=2))
    print(f"Updated cron_id to {args.cron_id}")


def cmd_shutdown(args):
    """Archive resolved observations, list designs/artifacts, delete state."""
    phash = get_phash(args)
    state_file = INSTANCES / f"{phash}.json"

    state = None
    cron_id = None
    if state_file.exists():
        state = json.loads(state_file.read_text())
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

    # Session observations — from full pre-archive list (includes items just archived)
    session_obs = pending
    if state and state.get("session_id"):
        session_obs = [o for o in pending if o.get("session") == state["session_id"]]

    designs = [f.name for f in sorted(DESIGNS.glob("*.md"))] if DESIGNS.exists() else []
    artifacts = read_jsonl(ARTIFACTS)

    if state_file.exists():
        state_file.unlink()

    print(json.dumps({
        "cron_id": cron_id,
        "archived_count": len(to_archive),
        "pending_count": len(remaining),
        "session_observations": session_obs,
        "designs": designs,
        "artifacts": artifacts,
    }, indent=2))


def cmd_observe(args):
    """Run session-digest and deduplicate against existing observations."""
    phash = get_phash(args)
    since = args.since or 5

    cmd = [sys.executable, str(DIGEST_SCRIPT), "--latest", f"--project={phash}", "--since", str(since), "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True)

    if r.returncode != 0:
        print(json.dumps({"digest": {"errors": [], "retries": []}, "existing_titles": [], "digest_error": r.stderr.strip()}))
        sys.exit(0)

    try:
        digest = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(json.dumps({"digest": {"errors": [], "retries": []}, "existing_titles": [], "digest_error": "invalid JSON from session-digest"}))
        sys.exit(0)

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
    state_file = INSTANCES / f"{phash}.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}

    date = datetime.now().strftime("%Y-%m-%d")
    pending_file = OBSERVATIONS / phash / "pending.jsonl"
    seq = next_obs_id(pending_file)

    obs = {
        "id": f"obs-{date}-{seq:03d}",
        "session": state.get("session_id", ""),
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
    state_file = INSTANCES / f"{phash}.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}

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
    state_file = INSTANCES / f"{phash}.json"
    pending_file = OBSERVATIONS / phash / "pending.jsonl"
    archive_file = OBSERVATIONS / phash / "archive.jsonl"

    print(json.dumps({
        "active": state_file.exists(),
        "instance": json.loads(state_file.read_text()) if state_file.exists() else None,
        "pending_observations": len(read_jsonl(pending_file)),
        "archived_observations": len(read_jsonl(archive_file)),
        "designs": len(list(DESIGNS.glob("*.md"))) if DESIGNS.exists() else 0,
        "artifacts": len(read_jsonl(ARTIFACTS)),
    }, indent=2))


def cmd_render_designer(args):
    """Render designer prompt. Looks up observation by ID from pending.jsonl."""
    phash = get_phash(args)
    cwd = args.cwd or os.getcwd()
    cli_path = str(SCRIPT_DIR / "workflow-improve.py")

    # Look up observation from pending
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
    })
    print(prompt)


def main():
    ap = argparse.ArgumentParser(description="Workflow improvement CLI")
    ap.add_argument("--project-hash", help="Override project hash (default: derived from cwd)")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("activate")
    p.add_argument("--cwd", help="Override working directory")

    p = sub.add_parser("set-cron-id")
    p.add_argument("cron_id")

    p = sub.add_parser("shutdown")

    p = sub.add_parser("observe")
    p.add_argument("--since", type=int, help="Minutes to look back (default 5)")

    p = sub.add_parser("record")
    p.add_argument("--category", required=True, help="failed-tool|repetition|manual-step|error-loop|missing-capability|slow-pattern|documentation-gap")
    p.add_argument("--impact", required=True, help="high|medium|low")
    p.add_argument("--title", required=True, help="Short description (<80 chars)")
    p.add_argument("--description", required=True, help="What happened")
    p.add_argument("--suggestion", default=None, help="Fix suggestion (optional)")

    p = sub.add_parser("register-artifact")
    p.add_argument("--file", required=True, help="Relative file path")
    p.add_argument("--type", required=True, help="created|modified")
    p.add_argument("--design-id", required=True, help="Associated design ID")
    p.add_argument("--description", required=True, help="What the artifact does")

    p = sub.add_parser("update-status")
    p.add_argument("obs_id")
    p.add_argument("status", help="pending|in-design|addressed|dismissed|duplicate")
    p.add_argument("--design-id", help="Link to design ID")

    p = sub.add_parser("status")

    p = sub.add_parser("render-designer")
    p.add_argument("--observation-id", required=True, help="Observation ID to look up")
    p.add_argument("--slug", required=True, help="Design slug")
    p.add_argument("--cwd", help="Override working directory")

    args = ap.parse_args()
    {
        "activate": cmd_activate,
        "set-cron-id": cmd_set_cron_id,
        "shutdown": cmd_shutdown,
        "observe": cmd_observe,
        "record": cmd_record,
        "register-artifact": cmd_register_artifact,
        "update-status": cmd_update_status,
        "status": cmd_status,
        "render-designer": cmd_render_designer,
    }[args.command](args)


if __name__ == "__main__":
    main()
