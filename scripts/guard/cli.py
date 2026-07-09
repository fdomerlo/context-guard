"""CLI entrypoint for guard middleware.

This is the ONLY module that calls sys.exit() and print().
All business logic is in commands.py.
"""

import argparse
import sys

from guard.commands import (
    cmd_check_lock,
    cmd_claim,
    cmd_release,
    cmd_claim_task,
    cmd_release_task,
    cmd_check_completion,
    cmd_validate,
    cmd_archive,
)
from guard.errors import GuardError


def parse_args(argv=None):
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Context Guard State Manager")
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
        "validate": lambda: cmd_validate(args.context),
        "archive": lambda: cmd_archive(args.context),
    }
    return handlers[args.command]()


def main(argv=None):
    """Main entrypoint. Parses args, dispatches, handles errors."""
    args = parse_args(argv)
    try:
        result = dispatch(args)
        print(result.message)
        sys.exit(result.exit_code)
    except GuardError as e:
        print(e.message)
        sys.exit(e.exit_code)


if __name__ == "__main__":
    main()
