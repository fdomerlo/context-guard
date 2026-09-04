import os
import subprocess
import tempfile
import pytest

from context_guard.guard.init_cmd import cmd_init


def run_hook(hook_path, message):
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        f.write(message)
        f_path = f.name
    try:
        res = subprocess.run(
            ["sh", hook_path, f_path],
            capture_output=True,
            text=True,
        )
        return res.returncode, res.stdout, res.stderr
    finally:
        if os.path.exists(f_path):
            os.remove(f_path)


def test_commit_msg_hook_valid_messages(tmp_path):
    hook_path = tmp_path / "commit-msg"
    from context_guard.guard.init_cmd import COMMIT_MSG_HOOK_SCRIPT
    hook_path.write_text(COMMIT_MSG_HOOK_SCRIPT)
    os.chmod(hook_path, 0o755)

    valid_messages = [
        "feat: add shiny new feature",
        "feat(core): add scoping support",
        "fix: resolve null pointer crash",
        "fix(parser): correctly handle escaped characters",
        "docs: update installation instructions in README",
        "refactor(db): streamline query caching layer",
        "test: add missing tests for authentication",
        "test(unit): verify date helper behavior",
        "chore: bump dependencies to latest versions",
        "chore(deps): bump pydantic to v2",
        "release: prepare version 1.2.0",
        "feat(api)!: break legacy parameter contract",
    ]

    for msg in valid_messages:
        rc, out, err = run_hook(str(hook_path), msg)
        assert rc == 0, f"Expected success for '{msg}', got {rc}. Output: {out + err}"


def test_commit_msg_hook_invalid_messages(tmp_path):
    hook_path = tmp_path / "commit-msg"
    from context_guard.guard.init_cmd import COMMIT_MSG_HOOK_SCRIPT
    hook_path.write_text(COMMIT_MSG_HOOK_SCRIPT)
    os.chmod(hook_path, 0o755)

    invalid_messages = [
        "WIP",
        "fixed issue with database",
        "Update README.md",
        "add test case",
        "feat:",
        "feat()",
        "unknown: unsupported type",
        "random commit message without convention",
    ]

    for msg in invalid_messages:
        rc, out, err = run_hook(str(hook_path), msg)
        assert rc != 0, f"Expected failure for '{msg}', got {rc}."
        assert "doesn't look like a conventional commit" in (out + err)


def test_commit_msg_hook_git_integration(tmp_path):
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    
    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "agent@example.com"], cwd=repo_dir, check=True)

    # Run cg init to install hooks and config
    res = cmd_init(str(repo_dir))
    assert res.exit_code == 0

    # Commit initial scaffold using bypass
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    bypass_env = {
        **os.environ,
        "CONTEXT_GUARD_BYPASS": "1",
        "CONTEXT_GUARD_BYPASS_REASON": "initial scaffold",
    }
    subprocess.run(
        ["git", "commit", "-m", "chore: initial scaffold"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        env=bypass_env,
    )

    # Now create and stage a single dummy file (under threshold=2 for pre-commit)
    dummy = repo_dir / "file.txt"
    dummy.write_text("hello")
    subprocess.run(["git", "add", "file.txt"], cwd=repo_dir, check=True)

    # 1. Invalid commit message should be rejected by commit-msg hook
    bad_commit = subprocess.run(
        ["git", "commit", "-m", "bad non conventional commit"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    assert bad_commit.returncode != 0
    assert "doesn't look like a conventional commit" in (bad_commit.stdout + bad_commit.stderr)

    # 2. Bypass with --no-verify should succeed
    bypass_commit = subprocess.run(
        ["git", "commit", "--no-verify", "-m", "bad commit but bypassed"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    assert bypass_commit.returncode == 0

    # 3. Valid conventional commit message should succeed without bypass
    dummy.write_text("world")
    subprocess.run(["git", "add", "file.txt"], cwd=repo_dir, check=True)
    good_commit = subprocess.run(
        ["git", "commit", "-m", "feat(test): add hello world content"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    assert good_commit.returncode == 0
