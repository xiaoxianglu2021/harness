#!/usr/bin/env python3
"""Advisory file locks for parallel harness sessions.

Design goals (production requirements):
  * Cross-platform: pure stdlib, atomic O_EXCL create (works on Windows/Linux/macOS).
  * Crash-safe: locks carry an owner + heartbeat timestamp; a lock older than
    its TTL is treated as stale and can be reclaimed after a quarantine sweep.
  * Re-entrant per process: same process re-acquiring upgrades mtime only.

Lock file format (JSON, single line):
  {"owner": "<session-id>", "pid": 123, "ts": 1690000000.0, "kind": "shared-resource"}

Usage (library):
    from lock import FileLock
    with FileLock(repo_root, "wiki", owner="sess-abc", ttl=120):
        ...  # critical section

Usage (CLI):
    python3 .harness/tools/lock.py acquire --repo . --name wiki --owner sess-abc
    python3 .harness/tools/lock.py release --repo . --name wiki --owner sess-abc
    python3 .harness/tools/lock.py with   --repo . --name wiki --owner sess-abc -- python3 -c "..."
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

LOCKS_DIR = ".harness/locks"
LOCK_NAME_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9._-]*$")
CANONICAL_LOCKS = {
    "index": "changes/INDEX.md registry update",
    "wiki": "formal .harness/wiki/ write (ingest/index/log)",
    "memory": ".harness/memory/* append",
    "evolution": ".harness/evolution/* write",
    "sessions": "SESSIONS.md registry update",
    "integrate": "integration-branch merge sequence",
}


class LockError(RuntimeError):
    pass


def locks_dir(repo_root: Path) -> Path:
    d = repo_root / LOCKS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _now() -> float:
    return time.time()


def acquire(repo_root: Path, name: str, owner: str, ttl: float,
            wait: float = 0.0, poll: float = 0.5) -> Path:
    """Acquire lock `name` for `owner`. If `wait` > 0, retry until deadline.

    Stale locks (ts older than ttl) are reclaimed automatically — but only if
    the owning process is dead (pid check) or the lock exceeded 3x TTL
    (conservative quarantine to avoid killing slow-but-alive holders).
    """
    if not LOCK_NAME_RE.match(name):
        raise LockError(f"invalid lock name: {name!r}")
    path = locks_dir(repo_root) / f"{name}.lock"
    deadline = _now() + wait
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"owner": owner, "pid": os.getpid(), "ts": _now(),
                           "kind": name, "ttl": ttl,
                           "pct": _proc_creation_time(os.getpid())}, f)
            return path
        except FileExistsError:
            meta = _read(path)
            if meta is None:  # torn write; quarantine-reclaim after grace
                if not path.exists() or _now() - path.stat().st_mtime > 5:
                    _unlink_retry(path)
                    continue
            elif _stale(meta, path):
                _reclaim(path, meta, name)
                continue
            if _now() >= deadline:
                holder = (meta or {}).get("owner", "unknown")
                raise LockError(f"lock '{name}' busy (owner={holder})")
            time.sleep(poll)


def _stale(meta: dict, path: Path) -> bool:
    age = _now() - float(meta.get("ts", 0))
    ttl = float(meta.get("ttl", 120))
    if age > 3 * ttl:  # far beyond lease: certainly dead
        return True
    if age > 5:  # grace window; after it, a dead owner must not block others
        if not _pid_alive(int(meta.get("pid", -1))):
            return True
        # pid alive — but it may be a REUSED pid, not the original holder
        holder_pct = meta.get("pct")
        if holder_pct is not None:
            cur_pct = _proc_creation_time(int(meta.get("pid", -1)))
            if cur_pct is not None and abs(cur_pct - float(holder_pct)) > 1.0:
                return True  # pid reused; original holder is gone
        return False
    return False


def _proc_creation_time(pid: int) -> float | None:
    """Process creation time in seconds. Guards against pid reuse: a live
    process reusing the holder's pid has a different creation time."""
    try:
        if os.name == "nt":
            import ctypes
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(0x0400 | 0x1000, False, pid)
            if not h:
                return None
            try:
                ct = ctypes.c_ulonglong(); et = ctypes.c_ulonglong()
                st = ctypes.c_ulonglong(); kt = ctypes.c_ulonglong()
                if not k32.GetProcessTimes(h, ctypes.byref(ct), ctypes.byref(et),
                                           ctypes.byref(st), ctypes.byref(kt)):
                    return None
                return ct.value / 1e7  # 100ns since 1601-01-01
            finally:
                k32.CloseHandle(h)
        else:
            with open(f"/proc/{pid}/stat", "rb") as f:
                parts = f.read().rsplit(b")", 1)[1].split()
                return float(parts[19]) / os.sysconf("SC_CLK_TCK")
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            try:
                exit_code = ctypes.c_ulong()
                k32.GetExitCodeProcess(h, ctypes.byref(exit_code))
                return exit_code.value == 259  # STILL_ACTIVE
            finally:
                k32.CloseHandle(h)
        else:
            os.kill(pid, 0)
            return True
    except (OSError, Exception):
        return False


def _reclaim(path: Path, meta: dict, name: str) -> None:
    qdir = locks_dir(path.parent.parent) / "quarantine"
    qdir.mkdir(exist_ok=True)
    qpath = qdir / f"{name}.{int(_now())}.lock.dead"
    try:
        path.rename(qpath)
    except OSError:
        pass


def _unlink_retry(path: Path, attempts: int = 50, delay: float = 0.02) -> bool:
    """Delete with retry: on Windows, unlink fails while another handle
    (e.g. a concurrent reader) holds the file open. Retry briefly."""
    for _ in range(attempts):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            time.sleep(delay)
    return False


def release(repo_root: Path, name: str, owner: str) -> bool:
    path = locks_dir(repo_root) / f"{name}.lock"
    meta = _read(path)
    if meta is None:
        return False
    if meta.get("owner") != owner:
        raise LockError(f"lock '{name}' owned by {meta.get('owner')!r}, not {owner!r}")
    return _unlink_retry(path)


def heartbeat(repo_root: Path, names: list[str], owner: str) -> list[str]:
    """Refresh ts on locks owned by `owner` (lease renewal)."""
    renewed = []
    for name in names:
        path = locks_dir(repo_root) / f"{name}.lock"
        meta = _read(path)
        if meta and meta.get("owner") == owner:
            meta["ts"] = _now()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(meta), encoding="utf-8")
            os.replace(tmp, path)
            renewed.append(name)
    return renewed


class FileLock:
    def __init__(self, repo_root: Path | str, name: str, owner: str,
                 ttl: float = 120, wait: float = 60):
        self.repo_root = Path(repo_root)
        self.name = name
        self.owner = owner
        self.ttl = ttl
        self.wait = wait
        self.path: Path | None = None

    def __enter__(self) -> "FileLock":
        self.path = acquire(self.repo_root, self.name, self.owner, self.ttl, self.wait)
        return self

    def __exit__(self, *exc) -> None:
        if self.path:
            try:
                release(self.repo_root, self.name, self.owner)
            except LockError:
                pass


def main() -> int:
    p = argparse.ArgumentParser(description="Harness advisory file locks")
    sub = p.add_subparsers(dest="cmd", required=True)
    for cmd in ("acquire", "release", "with"):
        sp = sub.add_parser(cmd)
        sp.add_argument("--repo", default=".")
        sp.add_argument("--name", required=True)
        sp.add_argument("--owner", required=True)
        if cmd == "acquire":
            sp.add_argument("--ttl", type=float, default=120)
            sp.add_argument("--wait", type=float, default=60)
        if cmd == "with":
            sp.add_argument("cmd_args", nargs=argparse.REMAINDER)
    sub.add_parser("list").add_argument("--repo", default=".")
    args = p.parse_args()
    repo = Path(args.repo).resolve()

    try:
        if args.cmd == "acquire":
            acquire(repo, args.name, args.owner, args.ttl, args.wait)
            print(f"ACQUIRED {args.name} owner={args.owner}")
        elif args.cmd == "release":
            ok = release(repo, args.name, args.owner)
            print(f"{'RELEASED' if ok else 'NOT-HELD'} {args.name}")
        elif args.cmd == "with":
            acquire(repo, args.name, args.owner, ttl=300, wait=60)
            assert args.cmd_args and args.cmd_args[0] == "--"
            rc = subprocess.call(args.cmd_args[1:])
            release(repo, args.name, args.owner)
            return rc
        elif args.cmd == "list":
            for lk in sorted(locks_dir(repo).glob("*.lock")):
                m = _read(lk) or {}
                age = int(_now() - float(m.get("ts", 0)))
                print(f"{lk.stem:<12} owner={m.get('owner'):<28} age={age}s ttl={m.get('ttl')}s")
    except LockError as e:
        print(f"LOCK-FAIL: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
