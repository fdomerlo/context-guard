"""CLI entrypoint for guard middleware.

This is the ONLY module that calls sys.exit() and print().
All business logic is in commands.py.
"""

import argparse
import json
import sys

from .commands import (
    cmd_approve,
    cmd_check_lock,
    cmd_new,
    cmd_setup,
    cmd_list,
    cmd_migrate,
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
    p_begin.add_argument("--context", default=".")
    p_begin.add_argument("--phase", required=True)
    p_begin.add_argument("--ttl", type=int, default=1800)

    p_commit = subparsers.add_parser("commit")
    p_commit.add_argument("--context", default=".")
    p_commit.add_argument("--next-phase", required=True)

    # Human-only: the agent must ask for this to be run, not run it. Pair it
    # with your harness's permission prompt (see adapters/*/PERMISSIONS.md).
    p_approve = subparsers.add_parser("approve")
    p_approve.add_argument("--context", default=".")
    p_approve.add_argument("--by", default=None,
                           help="Who is approving (required)")
    p_approve.add_argument("--hotfix", action="store_true",
                           help="Skip PLAN and open EXECUTE directly; requires --reason")
    p_approve.add_argument("--reason", default=None,
                           help="Why the pipeline is being skipped; persisted in the manifest")

    p_rollback = subparsers.add_parser("rollback")
    p_rollback.add_argument("--context", default=".")

    p_checkpoint = subparsers.add_parser("checkpoint")
    p_checkpoint.add_argument("--context", default=".")
    p_checkpoint.add_argument("--summary", required=True)

    # -- Sesión --
    p_check = subparsers.add_parser("check-lock")
    p_check.add_argument("--context", default=".")

    p_claim = subparsers.add_parser("claim")
    p_claim.add_argument("--context", default=".")
    p_claim.add_argument("--ttl", type=int, default=1800)

    p_acq = subparsers.add_parser("acquire")
    p_acq.add_argument("--context", default=".")
    p_acq.add_argument("--ttl", type=int, default=1800)

    p_release = subparsers.add_parser("release")
    p_release.add_argument("--context", default=".")
    p_release.add_argument("--agent-id", default=None,
                           help="Identity of the lock owner (required unless --force)")
    p_release.add_argument("--force", action="store_true",
                           help="Release regardless of ownership; recorded in the manifest")

    # -- Tareas --
    p_claim_task = subparsers.add_parser("claim-task")
    p_claim_task.add_argument("--context", default=".")
    p_claim_task.add_argument("--task-id", required=True)
    p_claim_task.add_argument("--agent-id", default=None)

    p_release_task = subparsers.add_parser("release-task")
    p_release_task.add_argument("--context", default=".")
    p_release_task.add_argument("--task-id", required=True)
    p_release_task.add_argument("--agent-id", default=None,
                                help="Validate ownership before release")
    p_release_task.add_argument("--force", action="store_true",
                                help="Skip ownership validation")

    # -- Utilidades --
    p_completion = subparsers.add_parser("check-completion")
    p_completion.add_argument("--context", default=".")

    p_validate = subparsers.add_parser("validate")
    p_validate.add_argument("--context", default=".")
    p_validate.add_argument("--max-length", type=int, default=None,
                            help="Override max artifact size")

    p_next = subparsers.add_parser("next-task")
    p_next.add_argument("--context", default=".")
    p_next.add_argument("--agent-id", default=None)

    p_status = subparsers.add_parser("status")
    p_status.add_argument("--context", default=".")

    p_doctor = subparsers.add_parser("doctor")
    p_doctor.add_argument("--context", default=".")
    p_doctor.add_argument("--fix", action="store_true",
                          help="Release task claims whose owning PID is gone")

    # -- Archive --
    p_archive = subparsers.add_parser("archive")
    p_archive.add_argument("--context", default=".")

    # -- Changes --
    p_new = subparsers.add_parser("new")
    p_new.add_argument("--context", default=".")
    p_new.add_argument("name")
    p_new.add_argument("--host", choices=["claude", "opencode", "antigravity"],
                       default=None,
                       help="Also materialise this host's workspace files "
                            "(Antigravity's rule file). Detected automatically "
                            "when omitted.")

    # setup takes no --context: it configures hosts, not a change. --project
    # opts back into 2.0's per-project install for teams committing the config.
    p_setup = subparsers.add_parser("setup")
    p_setup.add_argument("--host", choices=["claude", "opencode", "antigravity", "all"],
                         default="all")
    p_setup.add_argument("--with-mcp", action="store_true",
                         help="Also register the context-guard-mcp server. "
                              "Optional: every adapter works without it — MCP "
                              "is an alternative transport, not a requirement.")
    p_setup.add_argument("--project", default=None,
                         help="Install into this project instead of the user's "
                              "home directory.")
    p_setup.add_argument("--no-hooks", action="store_true",
                         help="Skip Antigravity's PreToolUse deny hook. That "
                              "hook is what stops the agent from running "
                              "cg approve itself; without it Antigravity has "
                              "no enforcement of the approval gate, only the "
                              "workspace rule asking it not to.")

    p_list = subparsers.add_parser("list")
    p_list.add_argument("--context", default=".")

    p_migrate = subparsers.add_parser("migrate")
    p_migrate.add_argument("--context", default=".")

    # Every context-scoped command accepts --change. Omitting it is only safe
    # when exactly one change is active; ambiguity is an error, never a guess.
    for sub in subparsers.choices.values():
        if sub in (p_list, p_new, p_migrate, p_setup):
            continue
        sub.add_argument("--change", default=None,
                         help="Change to operate on (required if several are active)")

    return parser.parse_args(argv)


def dispatch(args):
    """Route parsed args to the corresponding command function.

    Returns:
        CommandResult
    """
    change = getattr(args, "change", None)
    handlers = {
        "new": lambda: cmd_new(args.context, args.name, args.host),
        "setup": lambda: cmd_setup(
            host=args.host, with_mcp=args.with_mcp, project=args.project,
            no_hooks=args.no_hooks),
        "list": lambda: cmd_list(args.context),
        "migrate": lambda: cmd_migrate(args.context),
        "begin": lambda: cmd_begin(args.context, args.phase, args.ttl, change),
        "commit": lambda: cmd_commit(args.context, args.next_phase, change),
        "approve": lambda: cmd_approve(
            args.context, args.by, args.hotfix, args.reason, change),
        "rollback": lambda: cmd_rollback(args.context, change),
        "checkpoint": lambda: cmd_checkpoint(args.context, args.summary, change),
        "check-lock": lambda: cmd_check_lock(args.context, change),
        "claim": lambda: cmd_claim(args.context, args.ttl, change),
        "acquire": lambda: cmd_claim(args.context, args.ttl, change),  # alias
        "release": lambda: cmd_release(args.context, args.agent_id, args.force, change),
        "claim-task": lambda: cmd_claim_task(
            args.context, args.task_id, args.agent_id, change=change,
        ),
        "release-task": lambda: cmd_release_task(
            args.context, args.task_id, args.agent_id, args.force, change,
        ),
        "check-completion": lambda: cmd_check_completion(args.context, change),
        "validate": lambda: cmd_validate(
            args.context, getattr(args, "max_length", None), change),
        "next-task": lambda: cmd_next_task(
            args.context, getattr(args, "agent_id", None), change),
        "status": lambda: cmd_status(args.context, change),
        "doctor": lambda: cmd_doctor(args.context, args.fix, change),
        "archive": lambda: cmd_archive(args.context, change),
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
