"""Tag-pinning behaviour at the CLI layer.

We don't spin up Typer's runner or invoke real git here — we drive the
command functions directly with mocked collaborators (Git wrapper +
ConfigManager + DockerRuntime) and verify three things:

1. `agent add` / `channel add` clone with the right ref and persist it
   to config.json.
2. `agent rebuild` / `channel rebuild` read the persisted ref and call
   fetch_tags + checkout instead of pull --ff-only.
3. `--tag <new>` on rebuild overwrites the persisted pin.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ----- fixtures -------------------------------------------------------

@pytest.fixture
def fake_runtime():
    rt = MagicMock()
    rt.build.return_value = None
    rt.up.return_value = None
    rt.stop.return_value = None
    return rt


@pytest.fixture
def fake_git():
    return MagicMock()


# ----- agent rebuild --------------------------------------------------

def test_agent_rebuild_with_pinned_ref_uses_checkout(fake_git, fake_runtime):
    """When config has `ref` set, rebuild does fetch_tags + checkout —
    NOT pull_ff_only."""
    from cli.commands import agent_container

    conf = {
        "external_agents": {
            "ba": {
                "type": "github",
                "fragment_path": "/tmp/frag.yaml",
                "source_path": "/tmp/ba-src",
                "container_names": ["costaff-agent-ba"],
                "ref": "v0.1.0-alpha-1",
            }
        }
    }

    fake_git.is_repo.return_value = True

    with patch.object(agent_container.ConfigManager, "get_config", return_value=conf), \
         patch.object(agent_container.ConfigManager, "save_config") as save_mock, \
         patch.object(agent_container, "Git", return_value=fake_git), \
         patch.object(agent_container, "get_runtime", return_value=fake_runtime), \
         patch.object(agent_container, "load_dotenv"):
        agent_container.agent_rebuild(name="ba", no_cache=False, pull=True, tag=None)

    fake_git.fetch_tags.assert_called_once_with("/tmp/ba-src")
    fake_git.checkout.assert_called_once_with("/tmp/ba-src", "v0.1.0-alpha-1")
    fake_git.pull_ff_only.assert_not_called()
    # Config doesn't change — no explicit --tag was passed.
    save_mock.assert_not_called()


def test_agent_rebuild_without_pin_falls_back_to_pull(fake_git, fake_runtime):
    """No `ref` in config + no --tag override → preserve the legacy
    `git pull --ff-only` behaviour."""
    from cli.commands import agent_container

    conf = {
        "external_agents": {
            "ba": {
                "type": "github",
                "fragment_path": "/tmp/frag.yaml",
                "source_path": "/tmp/ba-src",
                "container_names": ["costaff-agent-ba"],
            }
        }
    }

    fake_git.is_repo.return_value = True

    with patch.object(agent_container.ConfigManager, "get_config", return_value=conf), \
         patch.object(agent_container.ConfigManager, "save_config"), \
         patch.object(agent_container, "Git", return_value=fake_git), \
         patch.object(agent_container, "get_runtime", return_value=fake_runtime), \
         patch.object(agent_container, "load_dotenv"):
        agent_container.agent_rebuild(name="ba", no_cache=False, pull=True, tag=None)

    fake_git.pull_ff_only.assert_called_once_with("/tmp/ba-src")
    fake_git.fetch_tags.assert_not_called()
    fake_git.checkout.assert_not_called()


def test_agent_rebuild_tag_override_writes_new_pin(fake_git, fake_runtime):
    """`--tag v0.2.0` on a repo that was previously pinned to alpha-1
    should: (a) checkout v0.2.0, and (b) persist the new ref to config."""
    from cli.commands import agent_container

    conf = {
        "external_agents": {
            "ba": {
                "type": "github",
                "fragment_path": "/tmp/frag.yaml",
                "source_path": "/tmp/ba-src",
                "container_names": ["costaff-agent-ba"],
                "ref": "v0.1.0-alpha-1",
            }
        }
    }
    fake_git.is_repo.return_value = True

    with patch.object(agent_container.ConfigManager, "get_config", return_value=conf), \
         patch.object(agent_container.ConfigManager, "save_config") as save_mock, \
         patch.object(agent_container, "Git", return_value=fake_git), \
         patch.object(agent_container, "get_runtime", return_value=fake_runtime), \
         patch.object(agent_container, "load_dotenv"):
        agent_container.agent_rebuild(name="ba", no_cache=False, pull=True, tag="v0.2.0")

    fake_git.checkout.assert_called_once_with("/tmp/ba-src", "v0.2.0")
    assert conf["external_agents"]["ba"]["ref"] == "v0.2.0"
    save_mock.assert_called_once()


def test_agent_rebuild_no_pull_skips_all_git_work(fake_git, fake_runtime):
    """`--no-pull` disables both legacy pull AND ref sync — the operator
    explicitly wants the working tree left alone."""
    from cli.commands import agent_container

    conf = {
        "external_agents": {
            "ba": {
                "type": "github",
                "fragment_path": "/tmp/frag.yaml",
                "source_path": "/tmp/ba-src",
                "container_names": ["costaff-agent-ba"],
                "ref": "v0.1.0-alpha-1",
            }
        }
    }
    fake_git.is_repo.return_value = True

    with patch.object(agent_container.ConfigManager, "get_config", return_value=conf), \
         patch.object(agent_container.ConfigManager, "save_config"), \
         patch.object(agent_container, "Git", return_value=fake_git), \
         patch.object(agent_container, "get_runtime", return_value=fake_runtime), \
         patch.object(agent_container, "load_dotenv"):
        agent_container.agent_rebuild(name="ba", no_cache=False, pull=False, tag=None)

    fake_git.pull_ff_only.assert_not_called()
    fake_git.fetch_tags.assert_not_called()
    fake_git.checkout.assert_not_called()


# ----- channel rebuild ------------------------------------------------

def test_channel_rebuild_with_pinned_ref_uses_checkout(fake_git, fake_runtime):
    from cli.commands import channel as channel_cmd

    conf = {
        "dynamic_channels": {
            "telegram": {
                "type": "github",
                "fragment_path": "/tmp/frag.yaml",
                "source_path": "/tmp/tg-src",
                "container_names": ["costaff-channel-telegram"],
                "public_port": 18090,
                "ref": "v0.1.0-alpha-1",
            }
        }
    }
    fake_git.is_repo.return_value = True

    fake_fragment_writer = MagicMock(return_value=("/tmp/frag.yaml", ["costaff-channel-telegram"], None))

    with patch.object(channel_cmd.ConfigManager, "get_config", return_value=conf), \
         patch.object(channel_cmd.ConfigManager, "save_config"), \
         patch.object(channel_cmd, "Git", return_value=fake_git), \
         patch.object(channel_cmd, "_write_channel_fragment", fake_fragment_writer), \
         patch.object(channel_cmd, "load_dotenv"), \
         patch.object(channel_cmd, "get_runtime", return_value=fake_runtime):
        channel_cmd.channel_rebuild(name="telegram", no_cache=False, pull=True, tag=None)

    fake_git.fetch_tags.assert_called_once_with("/tmp/tg-src")
    fake_git.checkout.assert_called_once_with("/tmp/tg-src", "v0.1.0-alpha-1")
    fake_git.pull_ff_only.assert_not_called()


def test_channel_rebuild_tag_override_writes_new_pin(fake_git, fake_runtime):
    from cli.commands import channel as channel_cmd

    conf = {
        "dynamic_channels": {
            "telegram": {
                "type": "github",
                "fragment_path": "/tmp/frag.yaml",
                "source_path": "/tmp/tg-src",
                "container_names": ["costaff-channel-telegram"],
                "public_port": 18090,
                "ref": "v0.1.0-alpha-1",
            }
        }
    }
    fake_git.is_repo.return_value = True

    fake_fragment_writer = MagicMock(return_value=("/tmp/frag.yaml", ["costaff-channel-telegram"], None))

    with patch.object(channel_cmd.ConfigManager, "get_config", return_value=conf), \
         patch.object(channel_cmd.ConfigManager, "save_config") as save_mock, \
         patch.object(channel_cmd, "Git", return_value=fake_git), \
         patch.object(channel_cmd, "_write_channel_fragment", fake_fragment_writer), \
         patch.object(channel_cmd, "load_dotenv"), \
         patch.object(channel_cmd, "get_runtime", return_value=fake_runtime):
        channel_cmd.channel_rebuild(name="telegram", no_cache=False, pull=True, tag="v0.2.0")

    fake_git.checkout.assert_called_once_with("/tmp/tg-src", "v0.2.0")
    assert conf["dynamic_channels"]["telegram"]["ref"] == "v0.2.0"
    save_mock.assert_called_once()


# ----- update (core) --------------------------------------------------

def test_update_with_tag_uses_fetch_and_checkout():
    """`costaff update --tag v0.1.0-alpha-1` must NOT fall back to
    `git pull --ff-only` — pull on detached HEAD would refuse anyway."""
    from cli.commands import update as update_cmd

    fake_git = MagicMock()
    with patch.object(update_cmd, "Git", return_value=fake_git), \
         patch.object(update_cmd, "subprocess") as sp_module:
        # The "any local modifications?" probe + the trailing pip install
        # both go through subprocess.run; only the pull-vs-checkout path
        # matters for this assertion.
        sp_module.run.return_value.stdout = ""
        sp_module.run.return_value.returncode = 0
        update_cmd.update(tag="v0.1.0-alpha-1")

    fake_git.fetch_tags.assert_called_once()
    fake_git.checkout.assert_called_once()
    args, _ = fake_git.checkout.call_args
    assert args[1] == "v0.1.0-alpha-1"


def test_update_without_tag_still_does_pull_ff_only():
    """Legacy path stays intact — no --tag means `git pull --ff-only`."""
    from cli.commands import update as update_cmd

    fake_git = MagicMock()
    with patch.object(update_cmd, "Git", return_value=fake_git), \
         patch.object(update_cmd, "subprocess") as sp_module:
        sp_module.run.return_value.stdout = ""
        sp_module.run.return_value.returncode = 0
        update_cmd.update(tag=None)

    fake_git.fetch_tags.assert_not_called()
    fake_git.checkout.assert_not_called()
    # subprocess.run was called for git pull (and other side effects).
    # Inspect the first call args list for the pull invocation.
    pull_calls = [
        c for c in sp_module.run.call_args_list
        if c.args and c.args[0][:3] == ["git", "pull", "--ff-only"]
    ]
    assert len(pull_calls) == 1
