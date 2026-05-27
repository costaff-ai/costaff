"""Unit tests for services.runtime.git."""
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from services.runtime.git import Git, GitError


def test_is_repo_true(tmp_path):
    (tmp_path / ".git").mkdir()
    assert Git().is_repo(tmp_path) is True


def test_is_repo_false_for_plain_dir(tmp_path):
    assert Git().is_repo(tmp_path) is False


def test_is_repo_false_when_git_is_a_file(tmp_path):
    (tmp_path / ".git").write_text("submodule pointer")
    assert Git().is_repo(tmp_path) is False


def test_clone_runs_expected_command(tmp_path):
    with patch("services.runtime.git.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        Git().clone("https://example.com/foo.git", tmp_path / "dest")
        args = mock_run.call_args[0][0]
        assert args[:2] == ["git", "clone"]
        assert "--depth" in args and args[args.index("--depth") + 1] == "1"
        assert args[-2:] == ["https://example.com/foo.git", str(tmp_path / "dest")]


def test_clone_omits_depth_when_zero(tmp_path):
    with patch("services.runtime.git.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        Git().clone("https://example.com/foo.git", tmp_path / "dest", depth=0)
        args = mock_run.call_args[0][0]
        assert "--depth" not in args


def test_clone_raises_giterror_on_non_zero(tmp_path):
    err = subprocess.CalledProcessError(128, ["git", "clone"], stderr="repo not found")
    with patch("services.runtime.git.subprocess.run", side_effect=err):
        with pytest.raises(GitError) as exc:
            Git().clone("https://example.com/missing.git", tmp_path / "dest")
        assert "repo not found" in str(exc.value)


def test_clone_raises_giterror_when_git_missing(tmp_path):
    with patch("services.runtime.git.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(GitError) as exc:
            Git().clone("https://example.com/foo.git", tmp_path / "dest")
        assert "git binary not found" in str(exc.value)


def test_pull_ff_only_runs_in_repo_cwd(tmp_path):
    with patch("services.runtime.git.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        Git().pull_ff_only(tmp_path)
        assert mock_run.call_args[0][0] == ["git", "pull", "--ff-only"]
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)


def test_pull_ff_only_raises_giterror_on_diverged_branch(tmp_path):
    err = subprocess.CalledProcessError(
        1, ["git", "pull"], stderr="fatal: Not possible to fast-forward"
    )
    with patch("services.runtime.git.subprocess.run", side_effect=err):
        with pytest.raises(GitError) as exc:
            Git().pull_ff_only(tmp_path)
        assert "fast-forward" in str(exc.value).lower()


# ---------- tag / ref-aware clone --------------------------------------

def test_clone_with_ref_passes_branch_flag(tmp_path):
    """Tag pinning: --branch <ref> appears in the command line. Git
    accepts both branch names and tag names there (`--branch v0.1.0`
    works exactly like `--branch main`)."""
    with patch("services.runtime.git.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        Git().clone("https://example.com/foo.git", tmp_path / "dest", ref="v0.1.0-alpha-1")
        args = mock_run.call_args[0][0]
        assert "--branch" in args
        assert args[args.index("--branch") + 1] == "v0.1.0-alpha-1"


def test_clone_without_ref_omits_branch_flag(tmp_path):
    with patch("services.runtime.git.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        Git().clone("https://example.com/foo.git", tmp_path / "dest")
        args = mock_run.call_args[0][0]
        assert "--branch" not in args


def test_clone_with_ref_and_depth_zero_for_full_history(tmp_path):
    """When the caller wants to checkout other refs later, depth=0 keeps
    full history. The two flags must coexist in the command line."""
    with patch("services.runtime.git.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        Git().clone("https://example.com/foo.git", tmp_path / "dest", ref="main", depth=0)
        args = mock_run.call_args[0][0]
        assert "--depth" not in args
        assert "--branch" in args


# ---------- fetch_tags ------------------------------------------------

def test_fetch_tags_runs_expected_command(tmp_path):
    with patch("services.runtime.git.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        Git().fetch_tags(tmp_path)
        assert mock_run.call_args[0][0] == ["git", "fetch", "--tags", "--prune", "origin"]
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)


def test_fetch_tags_raises_giterror_on_failure(tmp_path):
    err = subprocess.CalledProcessError(128, ["git", "fetch"], stderr="repository not found")
    with patch("services.runtime.git.subprocess.run", side_effect=err):
        with pytest.raises(GitError):
            Git().fetch_tags(tmp_path)


# ---------- checkout --------------------------------------------------

def test_checkout_runs_expected_command(tmp_path):
    with patch("services.runtime.git.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        Git().checkout(tmp_path, "v0.1.0-alpha-1")
        assert mock_run.call_args[0][0] == ["git", "checkout", "v0.1.0-alpha-1"]
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)


def test_checkout_unknown_ref_raises_giterror(tmp_path):
    err = subprocess.CalledProcessError(1, ["git", "checkout"], stderr="error: pathspec 'v9.9.9' did not match")
    with patch("services.runtime.git.subprocess.run", side_effect=err):
        with pytest.raises(GitError) as exc:
            Git().checkout(tmp_path, "v9.9.9")
        assert "did not match" in str(exc.value)


# ---------- current_ref -----------------------------------------------

def test_current_ref_returns_branch_when_attached(tmp_path):
    """`symbolic-ref` succeeds → that's the branch name, no fallback."""
    with patch("services.runtime.git.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="main\n", stderr=""
        )
        result = Git().current_ref(tmp_path)
        assert result == "main"
        # Only one call needed.
        assert mock_run.call_count == 1


def test_current_ref_returns_exact_tag_on_detached_head(tmp_path):
    """`symbolic-ref` fails (detached HEAD), `describe --exact-match` finds the tag."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "symbolic-ref":
            raise subprocess.CalledProcessError(128, cmd, stderr="fatal: ref HEAD is not a symbolic ref")
        if cmd[1] == "describe":
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="v0.1.0-alpha-1\n", stderr="")
        raise AssertionError(f"unexpected call: {cmd}")

    with patch("services.runtime.git.subprocess.run", side_effect=fake_run):
        result = Git().current_ref(tmp_path)
    assert result == "v0.1.0-alpha-1"
    assert len(calls) == 2  # symbolic-ref + describe


def test_current_ref_falls_back_to_short_sha(tmp_path):
    """Detached HEAD without a matching tag → return short SHA."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] in ("symbolic-ref", "describe"):
            raise subprocess.CalledProcessError(128, cmd, stderr="no match")
        if cmd[1] == "rev-parse":
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="abcdef0\n", stderr="")
        raise AssertionError(f"unexpected call: {cmd}")

    with patch("services.runtime.git.subprocess.run", side_effect=fake_run):
        result = Git().current_ref(tmp_path)
    assert result == "abcdef0"
    assert len(calls) == 3
