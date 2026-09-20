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


def cmd_bind(repo: Path, sid: str, change: str) -> int:
    """Take over an orphaned/abandoned session's change (parallel.md §1).
    The taking session must be dedicated: it must not own another change row."""
    if not SESSION_RE.match(sid):
        print("FAIL: bad session id")
        return 2
    rows = load_sessions(repo)
    taker = next((r for r in rows if r["id"] == sid), None)
    if taker is None or taker["status"] != "live":
        print(f"FAIL: taking session {sid} is not live")
        return 2
    if taker["change"] and taker["change"] != change:
        print(f"FAIL: session {sid} already owns change {taker['change']}; "
              f"takeover requires a dedicated session (see `adopt`)")
        return 2
    target = next((r for r in rows if r["change"] == change and r["id"] != sid), None)
    if target is None:
        print(f"FAIL: no other session bound to change: {change}")
        return 2
    if target["status"] == "live" and is_live(target, _default_ttl()):
        print(f"FAIL: change {change} still has a live owner {target['id']}")
        return 2
    with FileLock(repo, "sessions", owner=sid, ttl=120, wait=60):
        rows = load_sessions(repo)
        for r in rows:
            if r["id"] == sid:
                if r["status"] != "live":
                    print(f"FAIL: taking session {sid} is not live")
                    return 2
                r["note"] += f" ; took over {change} from {target['id']}"
            if r["id"] == target["id"]:
                r["status"] = "orphaned-handed-over"
                r["lease_ts"] = "0"
        _write_sessions_unlocked(repo, rows)
    with FileLock(repo, "index", owner=sid, ttl=120, wait=60):
        path = repo / ".harness/changes/INDEX.md"
        text = path.read_text(encoding="utf-8")
        import re as _re
        text = _re.sub(rf"(\| {change} \| active \| [^|]*\|) {target['id']} (\|)",
                       rf"\g<1> {sid} \g<2>", text, count=1)
        path.write_text(text, encoding="utf-8")
    print(f"BOUND {change} -> {sid} (previous owner {target['id']} retired)")
    return 0


def _default_ttl() -> int:
    return int(os.environ.get("HARNESS_LEASE_TTL", "900"))


def _max_sessions() -> int:
    return int(os.environ.get("HARNESS_MAX_SESSIONS", "8"))


def _scaffold_change(worktree: Path, change: str, flow: str, sid: str) -> None:
    """Validator-ready scaffold inside the session worktree (flow-specific)."""
    cdir = worktree / ".harness/changes" / change
    (cdir / "request_analysis").mkdir(parents=True, exist_ok=True)
    if flow == "Lite-flow":
        (cdir / "summary.md").write_text(
            f"# Summary — {change}\n\n"
            f"- **需求**: (待填写)\n"
            f"- **类型**: {change.split('-')[0]}\n"
            f"- **日期**: {change[-8:]}\n"
            f"- **状态**: active\n"
            f"- **Flow**: Lite-flow\n"
            f"- **Current step**: L1\n"
            f"- **Resume point**: phase-0\n"
            f"- **Session**: {sid}\n\n"
            f"## Inline lite spec\n\n- low_risk_proof: (待填写：机械可复核的低风险证据)\n",
            encoding="utf-8")
        (cdir / "request_analysis" / "checklist.md").write_text(
            "# Checklist\n\n- [ ] (待填写：仅限 checklist 范围内的修改项)\n",
            encoding="utf-8")
    else:
        (cdir / "summary.md").write_text(
            f"# Summary — {change}\n\n"
            f"- **需求**: (待填写)\n"
            f"- **类型**: {change.split('-')[0]}\n"
            f"- **日期**: {change[-8:]}\n"
            f"- **状态**: active\n"
            f"- **Flow**: Standard-flow\n"
            f"- **Current step**: Phase 1\n"
            f"- **Substep**: none\n"
            f"- **Resume point**: phase-0\n"
            f"- **Session**: {sid}\n", encoding="utf-8")
        (cdir / "request_analysis" / "understanding.md").write_text(
            "# Understanding\n\n(待填写)\n\n## Wiki Discovery\n\n"
            "- 已读 `.harness/wiki/index.md`：无相关页（新会话脚手架，待补充）\n",
            encoding="utf-8")
    print(f"SCAFFOLD {cdir / 'summary.md'} ({flow})")


def cmd_new(repo: Path, change: str, flow: str, ttl: int) -> int:
    if not CHANGE_RE.match(change):
        print(f"FAIL: change id does not match {{type}}-{{name}}-{{YYYYMMDD}}: {change}")
        return 2
    rows = load_sessions(repo)
    if any(r["change"] == change and r["status"] == "live" for r in rows):
        print(f"FAIL: change already bound to a live session: {change}")
        return 2
    live_now = sum(1 for r in rows if is_live(r, ttl))
    if live_now >= _max_sessions():
        print(f"FAIL: {live_now} live sessions >= HARNESS_MAX_SESSIONS={_max_sessions()}; "
              f"release or sweep before opening more")
        return 2
    sid = "sess-" + uuid.uuid4().hex[:8]
    branch = f"harness/{change}"
    worktree = Path(repo).parent / ".harness-worktrees" / change
    # Same-day retry / resume: branch and worktree survive release by design.
    existing_branch = _git(repo, "branch", "--list", branch)
    if not (worktree / ".git").exists():
        _git(repo, "worktree", "prune")
        if existing_branch:
            _git(repo, "worktree", "add", str(worktree), branch)  # reuse branch
        else:
            _git(repo, "worktree", "add", "-b", branch, str(worktree))
    # else: worktree already exists for this change — resume it

    with FileLock(repo, "sessions", owner=sid, ttl=120, wait=60):
        rows = load_sessions(repo)  # re-read under lock
        rows.append({"id": sid, "change": change, "branch": branch, "status": "live",
                     "lease_ts": str(int(time.time())), "note": flow})
        _write_sessions_unlocked(repo, rows)

    # Register the change row in the SHARED INDEX under the index lock.
    with FileLock(repo, "index", owner=sid, ttl=120, wait=60):
        _append_index_row(repo, change, sid)

    # Validator-ready scaffold inside the session worktree (private).
    _scaffold_change(worktree, change, flow, sid)

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
    """INDEX rows gain a 5th column `Session`. One row per change id:
    re-registering an existing change updates its row in place (retry)."""
    path = repo / ".harness/changes/INDEX.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    out, header_seen, updated = [], False, False
    for ln in lines:
        if ln.startswith("| Change |"):
            out.append("| Change | Status | Resume point | Session | Notes |")
            out.append("|--------|--------|--------------|---------|-------|")
            header_seen = True
            continue
        if ln.startswith("|--------"):
            continue
        if header_seen and ln.strip().startswith("|") and ln.split("|")[1].strip() == change:
            out.append(f"| {change} | active | phase-0 | {sid} | re-registered by session |")
            updated = True
            continue
        out.append(ln)
    if not header_seen:
        out = ["| Change | Status | Resume point | Session | Notes |",
               "|--------|--------|--------------|---------|-------|"] + out
    if not updated:
        out.append(f"| {change} | active | phase-0 | {sid} | created by session |")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _find(repo: Path, sid: str) -> dict:
    for r in load_sessions(repo):
        if r["id"] == sid:
            return r
    raise SessionError(f"unknown session: {sid}")


def cmd_heartbeat(repo: Path, sid: str) -> int:
    with FileLock(repo, "sessions", owner=sid, ttl=120, wait=60):
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


def cmd_adopt(repo: Path, change: str, ttl: int) -> int:
    """One-step takeover: create a fresh dedicated session bound to an
    EXISTING change row whose owner is not live (orphaned/expired)."""
    rows = load_sessions(repo)
    target = next((r for r in rows if r["change"] == change), None)
    if target is None:
        print(f"FAIL: unknown change: {change}")
        return 2
    if target["status"] == "live" and is_live(target, ttl):
        print(f"FAIL: change {change} still has a live owner {target['id']}")
        return 2
    sid = "sess-" + uuid.uuid4().hex[:8]
    branch = target["branch"]
    worktree = Path(repo).parent / ".harness-worktrees" / change
    if not (worktree / ".git").exists():
        _git(repo, "worktree", "prune")
        _git(repo, "worktree", "add", str(worktree), branch)
    with FileLock(repo, "sessions", owner=sid, ttl=120, wait=60):
        rows = load_sessions(repo)
        for r in rows:
            if r["id"] == target["id"]:
                r["status"] = "orphaned-handed-over"
                r["lease_ts"] = "0"
        rows.append({"id": sid, "change": change, "branch": branch, "status": "live",
                     "lease_ts": str(int(time.time())), "note": f"adopted from {target['id']}"})
        _write_sessions_unlocked(repo, rows)
    with FileLock(repo, "index", owner=sid, ttl=120, wait=60):
        _append_index_row(repo, change, sid)  # in-place rebind
    print(json.dumps({"session": sid, "change": change, "branch": branch,
                      "worktree": str(worktree), "adopted_from": target["id"]}))
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
    # Governance sync: ALL INDEX rows bound to this sid must follow the
    # session outcome (covers adopt/bind takeovers), under the index lock.
    with FileLock(repo, "index", owner=sid, ttl=120, wait=60):
        path = repo / ".harness/changes/INDEX.md"
        import re as _re
        text = path.read_text(encoding="utf-8")
        resume = "none" if status == "done" else "phase-0"
        text = _re.sub(
            rf"(\| [^|\n]+ \|) active (\|)[^|]*(\|)[^|]*{sid}[^|]*(\|)[^|]*(\|)",
            rf"\g<1> {status} \g<2> {resume} \g<3> {sid} \g<4> released by session \g<5>",
            text)
        path.write_text(text, encoding="utf-8")
    # Drop the worktree; branch (and merged commits) survive.
    worktree = Path(repo).parent / ".harness-worktrees" / row["change"]
    if worktree.exists() and not keep:
        _git(repo, "worktree", "remove", "--force", str(worktree), check=False)
    print(f"RELEASED {sid} status={status} (INDEX row synced)")
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
    with FileLock(repo, "sessions", owner="sweep", ttl=120, wait=60):
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
               HARNESS_BRANCH=row["branch"], HARNESS_MAIN_ROOT=str(repo))
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

    sp = sub.add_parser("adopt")
    sp.add_argument("--change", required=True)

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
        if args.cmd == "adopt":
            return cmd_adopt(repo, args.change, ttl)
        if args.cmd == "bind":
            return cmd_bind(repo, args.session, args.change)
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
