"""Tests for services.config_schema — Pydantic validation of config.json."""
import pytest
from pydantic import ValidationError

from services.config_schema import CoStaffConfig


def test_empty_config_validates():
    CoStaffConfig.model_validate({})


def test_minimal_real_config_validates():
    CoStaffConfig.model_validate({
        "mcp": ["costaff"],
        "channels": [],
        "external_agents": {},
        "dynamic_channels": {},
    })


def test_full_external_agent_validates():
    CoStaffConfig.model_validate({
        "external_agents": {
            "business-analysis": {
                "type": "github",
                "source_path": "/Users/x/.costaff/costaff-agent/business-analysis/src",
                "fragment_path": "/Users/x/.costaff/costaff-agent/business-analysis/compose-fragment.yaml",
                "a2a_url": "http://costaff-agent-business-analysis:8081",
                "public_port": 18110,
                "description": "BA agent",
                "version": "0.1.0",
                "enabled": True,
                "container_names": ["costaff-agent-business-analysis", "costaff-mcp-business-analysis"],
                "mcp_configurable": True,
                "mcp_env_var": "BUSINESS_ANALYSIS_AGENT_MCP_URLS",
                "model_env_var": "BUSINESS_ANALYSIS_AGENT_MODEL",
            }
        }
    })


def test_dynamic_channel_validates():
    CoStaffConfig.model_validate({
        "dynamic_channels": {
            "telegram": {
                "type": "github",
                "source_path": "/path/to/src",
                "fragment_path": "/path/to/fragment.yaml",
                "public_port": 18090,
                "description": "Telegram channel",
                "enabled": True,
                "container_names": ["costaff-channel-telegram"],
            }
        }
    })


def test_agent_mcp_filters_validates():
    CoStaffConfig.model_validate({
        "agent_mcp_filters": {
            "coding": {
                "costaff": ["send_message_now", "add_task_comment"],
            }
        }
    })


def test_external_mcp_string_form_validates():
    CoStaffConfig.model_validate({
        "external_mcp": {"github": "http://example.com/mcp"}
    })


def test_external_mcp_dict_form_validates():
    CoStaffConfig.model_validate({
        "external_mcp": {
            "github": {"url": "http://example.com/mcp", "enabled": True},
        }
    })


def test_extra_top_level_keys_allowed():
    """We use extra='allow' to avoid breaking existing deployments with legacy keys."""
    CoStaffConfig.model_validate({"some_legacy_key": "value", "another": [1, 2, 3]})


def test_extra_keys_inside_external_agent_allowed():
    CoStaffConfig.model_validate({
        "external_agents": {
            "x": {
                "type": "github",
                "a2a_url": "http://x:8081",
                "experimental_field": "future-use",
            }
        }
    })


# ---------------------------------------------------------------------------
# Validation failures — these should reject typos / wrong types
# ---------------------------------------------------------------------------

def test_external_agent_missing_a2a_url_fails():
    with pytest.raises(ValidationError):
        CoStaffConfig.model_validate({
            "external_agents": {"x": {"type": "github"}}
        })


def test_external_agent_missing_type_fails():
    with pytest.raises(ValidationError):
        CoStaffConfig.model_validate({
            "external_agents": {"x": {"a2a_url": "http://x:8081"}}
        })


def test_mcp_must_be_list_of_strings():
    with pytest.raises(ValidationError):
        CoStaffConfig.model_validate({"mcp": "costaff"})  # str instead of list


def test_agent_mcp_filters_wrong_shape_fails():
    """agent_mcp_filters must be Dict[str, Dict[str, List[str]]]."""
    with pytest.raises(ValidationError):
        CoStaffConfig.model_validate({
            "agent_mcp_filters": {"coding": "costaff"}  # str instead of dict
        })


def test_container_names_must_be_list():
    with pytest.raises(ValidationError):
        CoStaffConfig.model_validate({
            "external_agents": {
                "x": {
                    "type": "github",
                    "a2a_url": "http://x:8081",
                    "container_names": "costaff-agent-x",  # str instead of list
                }
            }
        })


def test_get_config_raises_on_corrupt_json(tmp_path):
    """Regression for GA audit: a hand-mangled config.json used to be
    silently swallowed (empty default returned) — and the next save_config
    overwrote the file, wiping every registered agent/channel/core."""
    from services.config import ConfigCorruptError, ConfigManager

    bad = tmp_path / "config.json"
    bad.write_text('{"channels": [,}')
    with pytest.raises(ConfigCorruptError):
        ConfigManager.get_config(str(bad))


def test_get_config_returns_defaults_when_file_missing(tmp_path):
    from services.config import ConfigManager

    conf = ConfigManager.get_config(str(tmp_path / "does-not-exist.json"))
    assert conf["external_agents"] == {}
    assert conf["mcp"] == ["costaff"]
