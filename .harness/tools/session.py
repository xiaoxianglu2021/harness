#!/usr/bin/env python3
"""Parallel session manager for the harness.

Each development session = one registered lease + one git worktree (physical
isolation) + one change bound in the shared INDEX.md (logical isolation).

Isolation model (see .harness/rules/parallel.md):
  * PRIVATE per session : worktree files, .harness/changes/{id}/ (lives on the
                          session branch), code edits, run artifacts.
  * SHARED, lock-gated  : changes/INDEX.md (index lock), .harness/wiki/
                          (wiki lock), .harness/memory/ (memory lock),
                          .harness/evolution/ (evolution lock), integration
                          branch (integrate lock).
  * SHARED, read-only   : .harness/rules/, .harness/agents/, .harness/skills/,
                          .harness/tools/ — versioned in git; changes require
                          the governance flow on the main branch.

Commands:
  new        --repo . --change feat-x-20260920 [--flow Lite-flow] [--ttl 900]
              register session, create worktree+branch, append INDEX row.
  heartbeat  --repo . --session sess-xxxx
  bind       --repo . --session sess-xxxx --change feat-y-20260920
  release    --repo . --session sess-xxxx [--status done|abandoned] [--keep-worktree]
  list       --repo .
  sweep      --repo .          reclaim sessions whose lease expired (quarantine)
  exec       --repo . --session sess-xxxx -- <command>   run cmd under session ctx
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lock import FileLock, LockError, locks_dir  # noqa: E402

SESSIONS_FILE = ".harness/sessions/SESSIONS.md"
WORKTREE_ROOT = "../.harness-worktrees"
CHANGE_RE = re.compile(r"^(feat|fix|refactor|perf|test|docs|chore)-[a-z0-9][a-z0-9-]*-\d{8}$")
SESSION_RE = re.compile(r"^sess-[0-9a-f]{8}$")
ROW_RE = re.compile(
    r"^\|\s*`?([^`|]+?)`?\s*\|\s*`?([^`|]+?)`?\s*\|\s*`?([^`|]+?)`?\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*$"
)


class SessionError(RuntimeError):
    pass


def _git(repo: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SessionError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def sessions_path(repo: Path) -> Path:
    return repo / SESSIONS_FILE


def load_sessions(repo: Path) -> list[dict]:
    if not sessions_path(repo).exists():
        return []
    rows = []
    for line in sessions_path(repo).read_text(encoding="utf-8").splitlines():
        m = ROW_RE.match(line)
        if not m or not m.group(1).startswith("sess-"):
            continue
        rows.append({"id": m.group(1), "change": m.group(2), "branch": m.group(3),
                     "status": m.group(4), "lease_ts": m.group(5), "note": m.group(6)})
    return rows


def is_live(row: dict, ttl: int) -> bool:
    if row["status"] != "live":
        return False
    try:
        return time.time() - float(row["lease_ts"]) < ttl
    except ValueError:
        return False


def cmd_new(repo: Path, change: str, flow: str, ttl: int) -> int:
    if not CHANGE_RE.match(change):
        print(f"FAIL: change id does not match {{type}}-{{name}}-{{YYYYMMDD}}: {change}")
        return 2
    rows = load_sessions(repo)
    if any(r["change"] == change and r["status"] == "live" for r in rows):
        print(f"FAIL: change already bound to a live session: {change}")
        return 2
    sid = "sess-" + uuid.uuid4().hex[:8]
    branch = f"harness/{change}"
    worktree = Path(repo).parent / ".harness-worktrees" / change
    _git(repo, "worktree", "add", "-b", branch, str(worktree))

    with FileLock(repo, "sessions", owner=sid, ttl=120, wait=60):
        rows = load_sessions(repo)  # re-read under lock
        rows.append({"id": sid, "change": change, "branch": branch, "status": "live",
                     "lease_ts": str(int(time.time())), "note": flow})
        _write_sessions_unlocked(repo, rows)

    # Register the change row in the SHARED INDEX under the index lock.
    with FileLock(repo, "index", owner=sid, ttl=120, wait=60):
        _append_index_row(repo, change, sid)

    print(json.dumps({"session": sid, "change": change, "branch": branch,
                      "worktree": str(worktree), "lease_ttl_s": ttl}))
    print(f"NEXT: cd {worktree}  # all work happens inside the worktree")
    return 0


def _write_sessions_unlocked(repo: Path, rows: list[dict]) -> None:
    lines = ["# Session Registry", "",
             "| Session | Change | Branch | Status | Lease ts | Notes |",
             "|---------|--------|--------|--------|----------|-------|"]
    for r in rows:
        lines.append("| {id} | {change} | {branch} | {status} | {lease_ts} | {note} |".format(**r))
    sessions_path(repo).parent.mkdir(parents=True, exist_ok=True)
    sessions_path(repo).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_index_row(repo: Path, change: str, sid: str) -> None:
    """INDEX rows gain a 5th column `Session`. Kept backward compatible."""
    path = repo / ".harness/changes/INDEX.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    out, header_seen, inserted = [], False, False
    for ln in lines:
        if ln.startswith("| Change |"):
            out.append("| Change | Status | Resume point | Session | Notes |")
            out.append("|--------|--------|--------------|---------|-------|")
            header_seen = True
            continue
        if ln.startswith("|--------"):
            continue
        out.append(ln)
        if header_seen and not inserted and (not ln.strip() or not ln.startswith("|")):
            out.insert(-1, f"| {change} | active | phase-0 | {sid} | created by session |")
            inserted = True
    if not inserted:
        out.append(f"| {change} | active | phase-0 | {sid} | created by session |")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _find(repo: Path, sid: str) -> dict:
    for r in load_sessions(repo):
        if r["id"] == sid:
            return r
    raise SessionError(f"unknown session: {sid}")


def cmd_heartbeat(repo: Path, sid: str) -> int:
    rows = load_sessions(repo)
    hit = False
    for r in rows:
        if r["id"] == sid and r["status"] == "live":
            r["lease_ts"] = str(int(time.time()))
            hit = True
    if not hit:
        print("FAIL: session not found or not live")
        return 2
    _write_sessions_unlocked(repo, rows)
    print(f"HEARTBEAT {sid}")
    return 0


def cmd_release(repo: Path, sid: str, status: str, keep: bool) -> int:
    row = _find(repo, sid)
    if status not in ("done", "abandoned"):
        status = "abandoned"
    rows = load_sessions(repo)
    for r in rows:
        if r["id"] == sid:
            r["status"] = status
            r["lease_ts"] = "0"
    _write_sessions_unlocked(repo, rows)
    # Drop the worktree; branch (and merged commits) survive.
    worktree = Path(repo).parent / ".harness-worktrees" / row["change"]
    if worktree.exists() and not keep:
        _git(repo, "worktree", "remove", "--force", str(worktree), check=False)
    print(f"RELEASED {sid} status={status}")
    return 0


def cmd_list(repo: Path, ttl: int) -> int:
    rows = load_sessions(repo)
    if not rows:
        print("(no sessions)")
    for r in rows:
        live = is_live(r, ttl)
        try:
            age = int(time.time() - float(r["lease_ts"]))
        except ValueError:
            age = -1
        flag = "LIVE " if live else ("STALE" if r["status"] == "live" else r["status"].upper())
        print(f"{flag:<9} {r['id']}  change={r['change']:<32} branch={r['branch']:<44} lease_age={age}s")
    return 0


def cmd_sweep(repo: Path, ttl: int) -> int:
    rows, changed = load_sessions(repo), 0
    for r in rows:
        if r["status"] == "live" and not is_live(r, ttl):
            r["status"] = "orphaned"
            r["note"] += " ; lease expired, quarantined by sweep"
            changed += 1
    if changed:
        _write_sessions_unlocked(repo, rows)
    print(f"SWEEP: {changed} session(s) quarantined")
    return 0


def cmd_exec(repo: Path, sid: str, cmd_args: list[str]) -> int:
    row = _find(repo, sid)
    worktree = Path(repo).parent / ".harness-worktrees" / row["change"]
    env = dict(os.environ, HARNESS_SESSION=sid, HARNESS_CHANGE=row["change"],
               HARNESS_BRANCH=row["branch"])
    cmd_heartbeat(repo, sid)
    return subprocess.call(cmd_args, cwd=str(worktree), env=env)


def main() -> int:
    p = argparse.ArgumentParser(description="Harness parallel session manager")
    p.add_argument("--repo", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("new")
    sp.add_argument("--change", required=True)
    sp.add_argument("--flow", default="Standard-flow", choices=["Lite-flow", "Standard-flow"])

    sp = sub.add_parser("heartbeat")
    sp.add_argument("--session", required=True)

    sp = sub.add_parser("bind")
    sp.add_argument("--session", required=True)
    sp.add_argument("--change", required=True)

    sp = sub.add_parser("release")
    sp.add_argument("--session", required=True)
    sp.add_argument("--status", choices=["done", "abandoned"], default="done")
    sp.add_argument("--keep-worktree", action="store_true")

    sub.add_parser("list")
    sub.add_parser("sweep")

    sp = sub.add_parser("exec")
    sp.add_argument("--session", required=True)
    sp.add_argument("cmd_args", nargs=argparse.REMAINDER)

    args = p.parse_args()
    repo = Path(args.repo).resolve()
    ttl = int(os.environ.get("HARNESS_LEASE_TTL", "900"))

    try:
        if args.cmd == "new":
            return cmd_new(repo, args.change, args.flow, ttl)
        if args.cmd == "heartbeat":
            return cmd_heartbeat(repo, args.session)
        if args.cmd == "release":
            return cmd_release(repo, args.session, args.status, args.keep_worktree)
        if args.cmd == "list":
            return cmd_list(repo, ttl)
        if args.cmd == "sweep":
            return cmd_sweep(repo, ttl)
        if args.cmd == "exec":
            return cmd_exec(repo, args.session, args.cmd_args)
    except (SessionError, LockError) as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
