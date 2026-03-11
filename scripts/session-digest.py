#!/usr/bin/env python3
"""Tail Claude Code session JSONL logs and output a compact friction digest."""
import argparse, json, subprocess, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"

def find_latest_log(project=None):
    pattern = f"{project}/*.jsonl" if project else "*/*.jsonl"
    logs = [p for p in PROJECTS_DIR.glob(pattern) if "subagents" not in p.parts]
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None

def tail_lines(path, n):
    return subprocess.run(
        ["tail", "-n", str(n), str(path)], capture_output=True, text=True
    ).stdout.splitlines()

def parse_ts(ts_str):
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return None

def digest(path, lines=500, since_minutes=None, after_ts=None):
    raw = tail_lines(path, lines)
    cutoff = (datetime.now(timezone.utc).timestamp() - since_minutes * 60) if since_minutes else None
    tool_map, errors, retries = {}, [], []
    tool_counts = defaultdict(int)
    prev_tool, consecutive, timestamps = None, 0, []
    turn_count, error_count, session_id = 0, 0, None
    last_ts = None

    def flush_retry():
        nonlocal prev_tool, consecutive
        if consecutive >= 2 and prev_tool:
            retries.append({"time": timestamps[-1] if timestamps else "", "tool": prev_tool, "count": consecutive, "context": "consecutive identical"})

    for line in raw:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = parse_ts(entry.get("timestamp"))
        if cutoff and ts and ts.timestamp() < cutoff:
            continue
        if after_ts and ts and ts <= after_ts:
            continue
        if not session_id:
            session_id = entry.get("sessionId", "")
        t = entry.get("type")
        ts_short = ts.strftime("%H:%M:%S") if ts else "?"
        if ts:
            timestamps.append(ts_short)
            last_ts = ts
        if t == "assistant":
            turn_count += 1
            for b in entry.get("message", {}).get("content", []):
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    name = b.get("name", "?")
                    tool_map[b.get("id", "")] = {"name": name, "time": ts_short}
                    tool_counts[name] += 1
                    if name == prev_tool:
                        consecutive += 1
                    else:
                        flush_retry()
                        prev_tool, consecutive = name, 1
        elif t == "user":
            content = entry.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_result" or not b.get("is_error"):
                    continue
                info = tool_map.get(b.get("tool_use_id", ""), {"name": "?", "time": "?"})
                mp = b.get("content", [])
                msg = mp[0].get("text", "")[:200] if isinstance(mp, list) and mp else str(mp)[:200]
                errors.append({"time": info["time"], "tool": info["name"], "message": msg})
                error_count += 1
        elif t == "system":
            for he in entry.get("hookErrors", []):
                errors.append({"time": ts_short, "tool": "hook", "message": str(he)[:200]})
                error_count += 1
    flush_retry()
    total = sum(tool_counts.values())
    return {
        "session": (session_id or "?")[:8],
        "period": {"start": timestamps[0] if timestamps else "?", "end": timestamps[-1] if timestamps else "?"},
        "last_seen": last_ts.isoformat() if last_ts else None,
        "turns": turn_count, "errors": errors, "retries": retries,
        "stats": {"tool_counts": dict(tool_counts), "error_rate": round(error_count / total, 3) if total else 0},
    }

def fmt_text(d):
    date = datetime.now().strftime("%Y-%m-%d")
    out = [f"SESSION {d['session']} | {date} {d['period']['start']}-{d['period']['end']} | {d['turns']} turns | {len(d['errors'])} errors"]
    if d["errors"]:
        out.append("ERRORS:")
        out.extend(f"  [{e['time']}] {e['tool']} FAIL: {e['message']}" for e in d["errors"])
    if d["retries"]:
        out.append("RETRIES:")
        out.extend(f"  [{r['time']}] {r['tool']} x{r['count']}: {r.get('context', '')}" for r in d["retries"])
    top = sorted(d["stats"]["tool_counts"].items(), key=lambda x: -x[1])[:8]
    out.append(f"STATS:\n  Tools: {' '.join(f'{n}({c})' for n, c in top)} | Error rate: {d['stats']['error_rate']:.1%}")
    return "\n".join(out)

def main():
    ap = argparse.ArgumentParser(description="Session JSONL digest")
    ap.add_argument("log_path", nargs="?", help="Explicit log file path")
    ap.add_argument("--latest", action="store_true", help="Auto-discover most recent log")
    ap.add_argument("--project", help="Filter to project hash (with --latest)")
    ap.add_argument("--lines", type=int, default=500, help="Tail N lines (default 500)")
    ap.add_argument("--since", type=int, help="Only entries from last N minutes")
    ap.add_argument("--after", help="Only entries after this ISO timestamp")
    ap.add_argument("--json", action="store_true", dest="json_out", help="JSON output")
    args = ap.parse_args()
    if args.latest:
        path = find_latest_log(args.project)
        if not path:
            print("No session logs found", file=sys.stderr); sys.exit(1)
    elif args.log_path:
        path = Path(args.log_path)
    else:
        ap.print_help(); sys.exit(1)
    if not path.exists():
        print(f"Log not found: {path}", file=sys.stderr); sys.exit(1)
    after_ts = None
    if args.after:
        after_ts = parse_ts(args.after)
    d = digest(path, lines=args.lines, since_minutes=args.since, after_ts=after_ts)
    if not d["turns"] and not d["errors"]:
        print("No activity found"); sys.exit(0)
    print(json.dumps(d, indent=2) if args.json_out else fmt_text(d))

if __name__ == "__main__":
    main()
