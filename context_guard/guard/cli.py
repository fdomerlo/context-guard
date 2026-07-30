"""CLI entrypoint for guard middleware.

This is the ONLY module that calls sys.exit() and print().
All business logic is in commands.py.
"""

import argparse
import json
import sys

from .commands import (
    cmd_check_lock,
    cmd_claim,
    cmd_release,
    cmd_claim_task,
    cmd_release_task,
    cmd_check_completion,
    cmd_validate,
    cmd_next_task,
    cmd_status,
    cmd_doctor,
    cmd_archive,
    cmd_begin,
    cmd_commit,
    cmd_rollback,
    cmd_checkpoint,
)
from .errors import GuardError


def parse_args(argv=None):
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Context Guard State Manager")
    parser.add_argument("--format", choices=["text", "json"], default="text",
                        help="Output format (default: text)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # -- Transacciones y Checkpoints --
    p_begin = subparsers.add_parser("begin")
    p_begin.add_argument("--context", required=True)
    p_begin.add_argument("--phase", required=True)
    p_begin.add_argument("--ttl", type=int, default=1800)

    p_commit = subparsers.add_parser("commit")
    p_commit.add_argument("--context", required=True)
    p_commit.add_argument("--next-phase", required=True)

    p_rollback = subparsers.add_parser("rollback")
    p_rollback.add_argument("--context", required=True)

    p_checkpoint = subparsers.add_parser("checkpoint")
    p_checkpoint.add_argument("--context", required=True)
    p_checkpoint.add_argument("--summary", required=True)

    # -- Sesión --
    p_check = subparsers.add_parser("check-lock")
    p_check.add_argument("--context", required=True)

    p_claim = subparsers.add_parser("claim")
    p_claim.add_argument("--context", required=True)
    p_claim.add_argument("--ttl", type=int, default=1800)

    p_acq = subparsers.add_parser("acquire")
    p_acq.add_argument("--context", required=True)
    p_acq.add_argument("--ttl", type=int, default=1800)

    p_release = subparsers.add_parser("release")
    p_release.add_argument("--context", required=True)

    # -- Tareas --
    p_claim_task = subparsers.add_parser("claim-task")
    p_claim_task.add_argument("--context", required=True)
    p_claim_task.add_argument("--task-id", required=True)
    p_claim_task.add_argument("--agent-id", default=None)

    p_release_task = subparsers.add_parser("release-task")
    p_release_task.add_argument("--context", required=True)
    p_release_task.add_argument("--task-id", required=True)
    p_release_task.add_argument("--agent-id", default=None,
                                help="Validate ownership before release")
    p_release_task.add_argument("--force", action="store_true",
                                help="Skip ownership validation")

    # -- Utilidades --
    p_completion = subparsers.add_parser("check-completion")
    p_completion.add_argument("--context", required=True)

    p_validate = subparsers.add_parser("validate")
    p_validate.add_argument("--context", required=True)
    p_validate.add_argument("--max-length", type=int, default=None,
                            help="Override max artifact size")

    p_next = subparsers.add_parser("next-task")
    p_next.add_argument("--context", required=True)
    p_next.add_argument("--agent-id", default=None)

    p_status = subparsers.add_parser("status")
    p_status.add_argument("--context", required=True)

    p_doctor = subparsers.add_parser("doctor")
    p_doctor.add_argument("--context", required=True)

    # -- Archive --
    p_archive = subparsers.add_parser("archive")
    p_archive.add_argument("--context", required=True)

    return parser.parse_args(argv)


def dispatch(args):
    """Route parsed args to the corresponding command function.

    Returns:
        CommandResult
    """
    handlers = {
        "begin": lambda: cmd_begin(args.context, args.phase, args.ttl),
        "commit": lambda: cmd_commit(args.context, args.next_phase),
        "rollback": lambda: cmd_rollback(args.context),
        "checkpoint": lambda: cmd_checkpoint(args.context, args.summary),
        "check-lock": lambda: cmd_check_lock(args.context),
        "claim": lambda: cmd_claim(args.context, args.ttl),
        "acquire": lambda: cmd_claim(args.context, args.ttl),  # alias
        "release": lambda: cmd_release(args.context),
        "claim-task": lambda: cmd_claim_task(
            args.context, args.task_id, args.agent_id,
        ),
        "release-task": lambda: cmd_release_task(
            args.context, args.task_id, args.agent_id, args.force,
        ),
        "check-completion": lambda: cmd_check_completion(args.context),
        "validate": lambda: cmd_validate(args.context, getattr(args, "max_length", None)),
        "next-task": lambda: cmd_next_task(args.context, getattr(args, "agent_id", None)),
        "status": lambda: cmd_status(args.context),
        "doctor": lambda: cmd_doctor(args.context),
        "archive": lambda: cmd_archive(args.context),
    }
    return handlers[args.command]()



def _to_json(message, exit_code, command=None):
    """Convert a command result message to JSON.

    Handles pipe-delimited (single-line), key=value (multi-line),
    and prose (multi-line) output formats.
    """
    lines = message.strip().split("\n")

    if len(lines) > 1:
        if any("=" in line.strip() for line in lines if line.strip()):
            return _kv_to_json(lines, exit_code, command)
        result = {"output": message.strip()}
        if command:
            result["command"] = command
        result["exit_code"] = exit_code
        return json.dumps(result)

    line = lines[0].strip()
    parts = line.split("|")
    result = {"status": parts[0]}
    if command:
        result["command"] = command
    if len(parts) > 1:
        result["action"] = parts[1]
    if len(parts) > 2:
        result["details"] = parts[2:]
    result["exit_code"] = exit_code
    return json.dumps(result)


def _kv_to_json(lines, exit_code, command=None):
    """Convert key=value lines to JSON. Used by check-completion."""
    result = {}
    if command:
        result["command"] = command
    current_source = None
    sources = []
    for line in lines:
        line = line.strip()
        if not line:
            if current_source:
                sources.append(current_source)
                current_source = None
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            if value == "true":
                value = True
            elif value == "false":
                value = False
            else:
                try:
                    value = int(value)
                except ValueError:
                    pass
            if key == "source":
                current_source = {"source": value}
            elif current_source is not None:
                current_source[key] = value
            else:
                result[key] = value
    if current_source:
        sources.append(current_source)
    if sources:
        result["sources"] = sources
    result["exit_code"] = exit_code
    return json.dumps(result)


def main(argv=None):
    """Main entrypoint. Parses args, dispatches, handles errors."""
    args = parse_args(argv)
    fmt = args.format
    try:
        result = dispatch(args)
        if fmt == "json":
            print(_to_json(result.message, result.exit_code, args.command))
        else:
            print(result.message)
        sys.exit(result.exit_code)
    except GuardError as e:
        if fmt == "json":
            print(_to_json(e.message, e.exit_code, args.command))
        else:
            print(e.message)
        sys.exit(e.exit_code)


if __name__ == "__main__":
    main()
