#!/usr/bin/env python3
"""MCP Server for Context Guard.

Exposes the transactional pipeline of context-guard as native MCP tools
over stdio transport. All persistent state lives in
`{context}/.context-guard/manifest.json`, where `context` is the absolute
path to the project directory.

Pipeline contract (strictly enforced):
    PLAN  ->  EXECUTE  ->  VERIFY  ->  ARCHIVE

A typical lifecycle:
    1. begin_transaction("/home/user/my-project", "PLAN")
    2. save_checkpoint("/home/user/my-project", "objective defined, tasks decomposed")
    3. commit_transaction("/home/user/my-project", "EXECUTE")
    4. begin_transaction("/home/user/my-project", "EXECUTE")
    5. ... work on tasks ...
    6. save_checkpoint("/home/user/my-project", "all tasks complete")
    7. commit_transaction("/home/user/my-project", "VERIFY")
    8. begin_transaction("/home/user/my-project", "VERIFY")
    9. ... run tests, validate artifacts ...
    10. commit_transaction("/home/user/my-project", "ARCHIVE")
"""

import os
import sys

from mcp.server.fastmcp import FastMCP
from context_guard.guard.transaction import (
    cmd_begin,
    cmd_commit,
    cmd_rollback,
    cmd_checkpoint,
)
from context_guard.guard.commands import (
    cmd_check_completion,
    cmd_next_task,
    cmd_status,
    cmd_validate,
)
from context_guard.guard.errors import GuardError, EXIT_GENERIC

mcp = FastMCP("context-guard")


def _format_result(fn, *args, **kwargs) -> str:
    """Execute a guard command function, unwrap CommandResult to a readable string."""
    try:
        res = fn(*args, **kwargs)
        return f"[{res.exit_code}] {res.message}"
    except GuardError as e:
        return f"[{e.exit_code}] {e.message}"
    except Exception as e:
        return f"[{EXIT_GENERIC}] FAIL|UNEXPECTED_ERROR|{str(e)}"


@mcp.tool()
def begin_transaction(context: str, phase: str, change: str | None = None) -> str:
    """Start a transactional phase in the 3-state pipeline.

    The pipeline enforces strict ordering: PLAN -> EXECUTE -> VERIFY -> ARCHIVE.
    You must begin a phase before doing work in it, and commit it before
    advancing to the next. Only one transaction can be active at a time per
    context; attempting to begin while another is in progress returns an error
    (unless the existing transaction has expired past its TTL).

    If phase is 'PLAN', this tool automatically scaffolds 5 markdown files in
    .context-guard/: objective.md, snapshot.md, tasks.md, review-report.md,
    and verify-report.md with default placeholder text if they do not exist.

    A snapshot of the current manifest state is captured automatically so that
    rollback_transaction can restore it if the phase fails.

    Args:
        context: ABSOLUTE PATH to the current project directory
                 (e.g. /home/user/workspace/my-project).
        phase: One of 'PLAN', 'EXECUTE', or 'VERIFY'. Any other value is rejected.

        change: OPTIONAL name of the change to operate on. Omit it when the
                project has exactly one active change; if several are active,
                omitting it is an error naming them, never a silent guess.

    Returns:
        '[0] SUCCESS|BEGIN|phase={phase}' on success, or an error string with
        a non-zero exit code.
    """
    return _format_result(cmd_begin, context, phase, change=change)


@mcp.tool()
def commit_transaction(context: str, next_phase: str, change: str | None = None) -> str:
    """Finalize the active phase and advance the pipeline to the next state.

    Validates that the transition is legal according to the DAG:
        PLAN -> EXECUTE,  EXECUTE -> VERIFY,  VERIFY -> ARCHIVE.
    Skipping phases (e.g. PLAN -> VERIFY) is rejected with EXIT_BAD_TRANSITION.

    Phase transitions will be rejected with EXIT_VALIDATION if required artifact
    files contain '[PENDING]' placeholder text or are missing:
    - PLAN -> EXECUTE requires completing objective.md and tasks.md.
    - VERIFY -> ARCHIVE requires completing review-report.md and verify-report.md.

    Committing consolidates state: marks the current phase as completed, updates
    lock_phase to next_phase, and generates a deterministic auto-summary.

    Args:
        context: ABSOLUTE PATH to the current project directory
                 (e.g. /home/user/workspace/my-project).
        next_phase: The phase to advance to. Must be the legal successor of the
                    currently active phase ('EXECUTE', 'VERIFY', or 'ARCHIVE').

        change: OPTIONAL name of the change to operate on. Omit it when the
                project has exactly one active change; if several are active,
                omitting it is an error naming them, never a silent guess.

    Returns:
        '[0] SUCCESS|COMMIT|lock_phase={next_phase}' on success, or an error
        string with a non-zero exit code.
    """
    return _format_result(cmd_commit, context, next_phase, change=change)


@mcp.tool()
def rollback_transaction(context: str, change: str | None = None) -> str:
    """Abort the active transaction and restore the pre-begin manifest snapshot.

    Use this when a phase fails (e.g. tests don't pass during VERIFY, or an
    execution step produces broken state). The manifest is rolled back to
    exactly the state it was in before begin_transaction was called, and the
    transaction status is reset to idle.

    Args:
        context: ABSOLUTE PATH to the current project directory
                 (e.g. /home/user/workspace/my-project).

        change: OPTIONAL name of the change to operate on. Omit it when the
                project has exactly one active change; if several are active,
                omitting it is an error naming them, never a silent guess.

    Returns:
        '[0] SUCCESS|ROLLBACK|restored' on success, or an error string with a
        non-zero exit code if no transaction is in progress.
    """
    return _format_result(cmd_rollback, context, change=change)


@mcp.tool()
def save_checkpoint(context: str, summary: str, change: str | None = None) -> str:
    """Persist a session summary as a lightweight checkpoint in manifest.json.

    Checkpoints serve as warm-boot state: if the agent loses context (e.g.
    session timeout, token limit), it can read the last checkpoint to resume.
    The summary is stored in manifest.json under session.session_summary.

    Note: commit_transaction also writes an auto-generated checkpoint, so
    manual checkpoints are mainly useful mid-phase to record intermediate
    progress before committing.

    Args:
        context: ABSOLUTE PATH to the current project directory
                 (e.g. /home/user/workspace/my-project).
        summary: Free-form text summarizing current progress. Maximum 2000
                 characters (~500 tokens). Exceeding the limit returns
                 EXIT_VALIDATION.

        change: OPTIONAL name of the change to operate on. Omit it when the
                project has exactly one active change; if several are active,
                omitting it is an error naming them, never a silent guess.

    Returns:
        '[0] SUCCESS|CHECKPOINT_SAVED' on success, or an error string with a
        non-zero exit code.
    """
    return _format_result(cmd_checkpoint, context, summary, change=change)


@mcp.tool()
def get_status(context: str, change: str | None = None) -> str:
    """Read the whole state of a change in one call, for warm-boot rehydration.

    Returns the context name, the first line of objective.md, task progress as
    completed/total, the next unclaimed pending task, and whether the session
    lock is held. This is the tool to call first after losing context: it is
    cheaper than reading the artifacts and it never guesses.

    Args:
        context: ABSOLUTE PATH to the current project directory.
        change: OPTIONAL name of the change to operate on. Omit it when the
                project has exactly one active change; if several are active,
                omitting it is an error naming them, never a silent guess.

    Returns:
        '[0] CONTEXT: ... / OBJECTIVE: ... / PROGRESS: n/m tasks complete /
        NEXT: ... / LOCK: ...' on success.
    """
    return _format_result(cmd_status, context, change)


@mcp.tool()
def check_completion(context: str, change: str | None = None) -> str:
    """Count the checkboxes in tasks.md deterministically.

    Use this instead of counting by eye before advancing a phase — the parser
    is the source of truth for whether the work is done, and it does not
    hallucinate a total.

    Args:
        context: ABSOLUTE PATH to the current project directory.
        change: OPTIONAL name of the change to operate on. Omit it when the
                project has exactly one active change; if several are active,
                omitting it is an error naming them, never a silent guess.

    Returns:
        '[0] source=tasks.md / total=N / completed=M / all_complete=true|false'.
    """
    return _format_result(cmd_check_completion, context, change)


@mcp.tool()
def validate(context: str, change: str | None = None) -> str:
    """Lint the session artifacts: existence, size cap, and language.

    Requires objective.md, snapshot.md and tasks.md to exist; checks every
    artifact against the size cap and rejects Spanish text (artifacts are
    English by contract). Does NOT check for leftover '[PENDING]' markers —
    that is enforced by commit_transaction.

    Args:
        context: ABSOLUTE PATH to the current project directory.
        change: OPTIONAL name of the change to operate on. Omit it when the
                project has exactly one active change; if several are active,
                omitting it is an error naming them, never a silent guess.

    Returns:
        '[0] SUCCESS|VALIDATE_OK', or '[4]' followed by one FAIL line per
        problem found.
    """
    return _format_result(cmd_validate, context, None, change)


@mcp.tool()
def next_task(context: str, change: str | None = None,
              agent_id: str | None = None) -> str:
    """Claim the next pending task in tasks.md and return it.

    Not read-only: the claim is taken atomically as part of the same call,
    which is what makes it safe for several agents to work one change at once.
    The returned agent_id is the identity that won the claim — keep it, since
    releasing the task requires passing it back.

    Claims carry a lease; a task whose lease expired is treated as abandoned
    and handed to the next caller, with the takeover recorded in the manifest.

    Args:
        context: ABSOLUTE PATH to the current project directory.
        change: OPTIONAL name of the change to operate on. Omit it when the
                project has exactly one active change; if several are active,
                omitting it is an error naming them, never a silent guess.
        agent_id: OPTIONAL identity to claim as. Generated if omitted.

    Returns:
        '[0] SUCCESS|NEXT_TASK|{task_id}|{agent_id}|{description}', or
        '[0] DONE|NO_PENDING_TASKS' when nothing is left.
    """
    return _format_result(cmd_next_task, context, agent_id, change)


# Deliberately NOT exposed as a tool: `approve`. PLAN.md 0.6 names the
# harness's permission prompt on `cg approve` as the only hard control in the
# enforcement model, and an MCP tool is precisely the channel that routes
# around it. The MCP is a transport; the human's confirmation is not.


def main():
    """Run FastMCP server over stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
