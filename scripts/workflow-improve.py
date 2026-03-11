#!/usr/bin/env python3
"""Workflow improvement CLI — handles all deterministic bookkeeping for the skill."""
import argparse, json, os, subprocess, sys, uuid
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
RENDER_SCRIPT = SCRIPT_DIR / "render_template.sh"
OBSERVER_TEMPLATE = SKILL_DIR / "references" / "observer.md"
DESIGNER_TEMPLATE = SKILL_DIR / "references" / "designer.md"


def project_hash(cwd):
    return cwd.replace("/", "-")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path):
    if not path.exists():
        return []
    lines = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return lines


def write_jsonl(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(i) for i in items) + "\n" if items else "")


def append_jsonl(path, item):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(item) + "\n")


def render_template(template_path, variables):
    """Call render_template.sh and return rendered text."""
    args = [f'{k}={v}' for k, v in variables.items()]
    cmd = f'source {RENDER_SCRIPT} && render_template {template_path} ' + ' '.join(f'"{a}"' for a in args)
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"render_template failed: {r.stderr}", file=sys.stderr)
        sys.exit(1)
    return r.stdout


def cmd_activate(args):
    """Setup steps 1-4, 6: discover env, check stale, mkdir, render prompt, write state."""
    cwd = args.cwd or os.getcwd()
    phash = project_hash(cwd)
    date = datetime.now().strftime("%Y-%m-%d")
    session_id = str(uuid.uuid4())

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
    workflow_improve_path = str(SCRIPT_DIR / "workflow-improve.py")
    observer_prompt = render_template(OBSERVER_TEMPLATE, {
        "CWD": cwd,
        "PROJECT_HASH": phash,
        "DATE": date,
        "SESSION_ID": session_id,
        "WORKFLOW_IMPROVE_PATH": workflow_improve_path,
    })

    # Write state file (cron_id filled later by agent after CronCreate)
    state = {
        "instance_id": str(uuid.uuid4()),
        "cron_id": None,
        "session_id": session_id,
        "project": cwd,
        "project_hash": phash,
        "started_at": now_iso(),
    }
    state_file.write_text(json.dumps(state, indent=2))

    result = {
        "project_hash": phash,
        "session_id": session_id,
        "date": date,
        "state_file": str(state_file),
        "observer_prompt": observer_prompt,
        "observations_dir": str(OBSERVATIONS),
        "designs_dir": str(DESIGNS),
        "artifacts_registry": str(ARTIFACTS),
    }
    if stale_info:
        result["stale_instance"] = stale_info
    print(json.dumps(result, indent=2))


def cmd_set_cron_id(args):
    """Update state file with cron ID after CronCreate."""
    phash = args.project_hash or project_hash(os.getcwd())
    state_file = INSTANCES / f"{phash}.json"
    if not state_file.exists():
        print("No active instance", file=sys.stderr)
        sys.exit(1)
    state = json.loads(state_file.read_text())
    state["cron_id"] = args.cron_id
    state_file.write_text(json.dumps(state, indent=2))
    print(f"Updated cron_id to {args.cron_id}")


def cmd_shutdown(args):
    """Shutdown steps 1, 3, 5-7: read state, archive, list designs/artifacts, delete state."""
    phash = args.project_hash or project_hash(os.getcwd())
    state_file = INSTANCES / f"{phash}.json"

    # Read state
    state = None
    cron_id = None
    if state_file.exists():
        state = json.loads(state_file.read_text())
        cron_id = state.get("cron_id")

    # Archive observations
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

    # Session observations (filter by session if state available)
    session_obs = pending  # all current pending
    if state and state.get("session_id"):
        sid = state["session_id"]
        session_obs = [o for o in pending if o.get("session") == sid]

    # List designs
    designs = []
    if DESIGNS.exists():
        designs = [f.name for f in sorted(DESIGNS.glob("*.md"))]

    # List artifacts
    artifacts = read_jsonl(ARTIFACTS)

    # Delete state file
    if state_file.exists():
        state_file.unlink()

    result = {
        "cron_id": cron_id,
        "archived_count": len(to_archive),
        "pending_count": len(remaining),
        "session_observations": session_obs,
        "designs": designs,
        "artifacts": artifacts,
    }
    print(json.dumps(result, indent=2))


def cmd_observe(args):
    """Observer steps 1-2: run session-digest, deduplicate against existing."""
    phash = args.project_hash or project_hash(os.getcwd())
    since = args.since or 5

    # Run session-digest
    cmd = [sys.executable, str(DIGEST_SCRIPT), "--latest", f"--project={phash}", "--since", str(since), "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(json.dumps({"new_friction": [], "digest_error": r.stderr.strip()}))
        sys.exit(0)

    try:
        digest = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(json.dumps({"new_friction": [], "digest_error": "invalid JSON from session-digest"}))
        sys.exit(0)

    # Check existing observations for dedup
    pending_file = OBSERVATIONS / phash / "pending.jsonl"
    existing = read_jsonl(pending_file)
    existing_titles = {o.get("title", "").lower() for o in existing}

    # Compute next observation ID
    existing_ids = [o.get("id", "") for o in existing]
    date = datetime.now().strftime("%Y-%m-%d")
    max_seq = 0
    for oid in existing_ids:
        parts = oid.split("-")
        if len(parts) >= 4:
            try:
                max_seq = max(max_seq, int(parts[-1]))
            except ValueError:
                pass

    result = {
        "digest": digest,
        "existing_count": len(existing),
        "existing_titles": sorted(existing_titles),
        "next_seq": max_seq + 1,
        "date": date,
        "pending_file": str(pending_file),
    }
    print(json.dumps(result, indent=2))


def cmd_record(args):
    """Append an observation to pending.jsonl."""
    obs = json.loads(args.obs_json)
    phash = obs.get("project", "").replace("/", "-") or args.project_hash or project_hash(os.getcwd())
    pending_file = OBSERVATIONS / phash / "pending.jsonl"
    append_jsonl(pending_file, obs)
    print(f"Recorded {obs.get('id', '?')} to {pending_file}")


def cmd_register_artifact(args):
    """Append an artifact to artifacts.jsonl."""
    artifact = json.loads(args.json)
    append_jsonl(ARTIFACTS, artifact)
    print(f"Registered artifact: {artifact.get('file', '?')}")


def cmd_update_status(args):
    """Update an observation's status in pending.jsonl."""
    phash = args.project_hash or project_hash(os.getcwd())
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
    phash = args.project_hash or project_hash(os.getcwd())
    state_file = INSTANCES / f"{phash}.json"
    pending_file = OBSERVATIONS / phash / "pending.jsonl"
    archive_file = OBSERVATIONS / phash / "archive.jsonl"

    result = {
        "active": state_file.exists(),
        "instance": json.loads(state_file.read_text()) if state_file.exists() else None,
        "pending_observations": len(read_jsonl(pending_file)),
        "archived_observations": len(read_jsonl(archive_file)),
        "designs": len(list(DESIGNS.glob("*.md"))) if DESIGNS.exists() else 0,
        "artifacts": len(read_jsonl(ARTIFACTS)),
    }
    print(json.dumps(result, indent=2))


def cmd_render_designer(args):
    """Render designer prompt with provided variables."""
    cwd = args.cwd or os.getcwd()
    workflow_improve_path = str(SCRIPT_DIR / "workflow-improve.py")
    prompt = render_template(DESIGNER_TEMPLATE, {
        "CWD": cwd,
        "DATE": datetime.now().strftime("%Y-%m-%d"),
        "OBSERVATION_JSON": args.observation_json,
        "OBSERVATION_ID": args.observation_id,
        "DESIGNS_DIR": str(DESIGNS),
        "SLUG": args.slug,
        "WORKFLOW_IMPROVE_PATH": workflow_improve_path,
    })
    print(prompt)


def main():
    ap = argparse.ArgumentParser(description="Workflow improvement CLI")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("activate", help="Setup: discover env, check stale, mkdir, render prompt, write state")
    p.add_argument("--cwd", help="Override working directory")

    p = sub.add_parser("set-cron-id", help="Update state file with cron ID after CronCreate")
    p.add_argument("cron_id", help="Cron task ID")
    p.add_argument("--project-hash", help="Override project hash")

    p = sub.add_parser("shutdown", help="Archive observations, list designs/artifacts, clean up state")
    p.add_argument("--project-hash", help="Override project hash")

    p = sub.add_parser("observe", help="Run session-digest and deduplicate against existing observations")
    p.add_argument("--project-hash", help="Override project hash")
    p.add_argument("--since", type=int, help="Minutes to look back (default 5)")

    p = sub.add_parser("record", help="Append an observation to pending.jsonl")
    p.add_argument("obs_json", help="Observation JSON string")
    p.add_argument("--project-hash", help="Override project hash")

    p = sub.add_parser("register-artifact", help="Append an artifact to artifacts.jsonl")
    p.add_argument("json", help="Artifact JSON string")

    p = sub.add_parser("update-status", help="Update observation status")
    p.add_argument("obs_id", help="Observation ID")
    p.add_argument("status", help="New status")
    p.add_argument("--design-id", help="Link to design ID")
    p.add_argument("--project-hash", help="Override project hash")

    p = sub.add_parser("status", help="Quick status view")
    p.add_argument("--project-hash", help="Override project hash")

    p = sub.add_parser("render-designer", help="Render designer prompt")
    p.add_argument("--observation-json", required=True, help="Observation JSON")
    p.add_argument("--observation-id", required=True, help="Observation ID")
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
