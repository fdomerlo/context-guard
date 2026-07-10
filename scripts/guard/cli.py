"""CLI entrypoint for guard middleware.

This is the ONLY module that calls sys.exit() and print().
All business logic is in commands.py.
"""

import argparse
import json
import sys

from guard.commands import (
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
    cmd_load_skill,
)
from guard.errors import GuardError


def parse_args(argv=None):
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Context Guard State Manager")
    parser.add_argument("--format", choices=["text", "json"], default="text",
                        help="Output format (default: text)")
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    p_load_skill = subparsers.add_parser("load-skill")
    p_load_skill.add_argument("--skill", required=True, help="Skill name (e.g. review)")

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
        "load-skill": lambda: cmd_load_skill(args.skill),
    }
    return handlers[args.command]()


def _to_json(message, exit_code, command=None):
    """Convert a pipe-delimited message to a JSON object.

    Handles both single-line (e.g. 'SUCCESS|LOCK_ACQUIRED') and
    multi-line key=value output (e.g. check-completion).
    """
    lines = message.strip().split("\n")

    # Check if output is key=value format (check-completion, status)
    if any("=" in line for line in lines if line.strip()):
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
                # Try to parse as number or boolean
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

    # Pipe-delimited format: STATUS|ACTION|details...
    parts = message.split("|")
    result = {"status": parts[0]}
    if command:
        result["command"] = command
    if len(parts) > 1:
        result["action"] = parts[1]
    if len(parts) > 2:
        result["details"] = parts[2:]
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
