#!/usr/bin/env python3
import argparse
import json
import os
import time
import socket
from datetime import datetime

MANIFEST_PATH = ".context-guard/active_session/manifest.json"
ARCHIVE_PATH = ".context-guard/archive/"
LOCK_FILE = ".context-guard/active_session/.lock"


def load_manifest():
    if not os.path.exists(MANIFEST_PATH):
        return None
    with open(MANIFEST_PATH, "r") as f:
        return json.load(f)


def save_manifest(data):
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    tmp_path = MANIFEST_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.rename(tmp_path, MANIFEST_PATH)


def cmd_check_lock(args):
    m = load_manifest()
    if not m or not m.get("lock", {}).get("held", False):
        print("FREE")
        return

    acquired = datetime.fromisoformat(m["lock"]["acquired_at"])
    elapsed = int((datetime.now() - acquired).total_seconds())
    ttl = m["lock"].get("ttl_seconds", 1800)

    if elapsed > ttl:
        print(f"STALE|{elapsed}|{ttl}")
    else:
        print(f"ACTIVE|{elapsed}|{ttl}|{m['lock'].get('acquired_by')}")


def _try_create_lockfile():
    """Atomic test-and-set at the OS level. Returns True if acquired."""
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def cmd_acquire(args):
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    m = load_manifest()
    if not m:
        m = {
            "context_name": args.context,
            "lock": {},
            "reference_docs": [],
            "files_in_scope": [],
        }

    if not _try_create_lockfile():
        # Someone else won the race between check-lock and this acquire.
        # Only override if their lock is stale per TTL.
        existing = m.get("lock", {})
        acquired_at = existing.get("acquired_at")
        ttl = existing.get("ttl_seconds", args.ttl)
        stale = False
        if acquired_at:
            elapsed = (
                datetime.now() - datetime.fromisoformat(acquired_at)
            ).total_seconds()
            stale = elapsed > ttl

        if not stale:
            print(f"FAIL|LOCK_HELD|{existing.get('acquired_by')}")
            return

        os.remove(LOCK_FILE)
        if not _try_create_lockfile():
            # Lost a second race against another stale-takeover attempt.
            print("FAIL|LOCK_CONTENDED")
            return

    m["lock"] = {
        "held": True,
        "acquired_at": datetime.now().isoformat(),
        "acquired_by": f"{os.getpid()}-{socket.gethostname()}-{int(time.time())}",
        "ttl_seconds": args.ttl,
    }
    save_manifest(m)
    print("SUCCESS|LOCK_ACQUIRED")


def cmd_release(args):
    m = load_manifest()
    if m and "lock" in m:
        m["lock"]["held"] = False
        m["lock"]["acquired_at"] = None
        m["lock"]["acquired_by"] = None
        save_manifest(m)
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
    print("SUCCESS|LOCK_RELEASED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Context Guard State Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check-lock")

    p_acq = subparsers.add_parser("acquire")
    p_acq.add_argument("--context", required=True)
    p_acq.add_argument("--ttl", type=int, default=1800)

    subparsers.add_parser("release")

    args = parser.parse_args()
    if args.command == "check-lock":
        cmd_check_lock(args)
    elif args.command == "acquire":
        cmd_acquire(args)
    elif args.command == "release":
        cmd_release(args)
