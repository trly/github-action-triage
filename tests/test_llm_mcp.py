import pytest
from pydantic import SecretStr
from github_action_triage.app.llm.mcp import (
    create_sourcegraph_mcp_server,
    MCP_SOURCEGRAPH_SERVER_NAME,
)
from github_action_triage.app.config.settings import Settings


@pytest.fixture
def settings_with_token():
    return Settings(
        sourcegraph_token=SecretStr("test-token-123"),
        sourcegraph_mcp_url="https://sourcegraph.example.com/.api/mcp/v1",
    )


@pytest.fixture
def settings_without_token():
    return Settings(
        sourcegraph_token=SecretStr(""),
        sourcegraph_mcp_url="https://sourcegraph.example.com/.api/mcp/v1",
    )


@pytest.fixture
def settings_without_url():
    return Settings(
        sourcegraph_token=SecretStr("test-token-123"), sourcegraph_mcp_url=""
    )


def test_mcp_server_name_constant():
    assert MCP_SOURCEGRAPH_SERVER_NAME == "sourcegraph"


def test_create_sourcegraph_mcp_server_with_valid_token(settings_with_token):
    result = create_sourcegraph_mcp_server(settings_with_token)

    assert result is not None
    assert MCP_SOURCEGRAPH_SERVER_NAME in result

    server_config = result[MCP_SOURCEGRAPH_SERVER_NAME]
    assert server_config["type"] == "sse"
    assert server_config["url"] == "https://sourcegraph.example.com/.api/mcp/v1"
    assert server_config["headers"]["Authorization"] == "token test-token-123"


def test_create_sourcegraph_mcp_server_without_token_returns_none(
    settings_without_token, caplog
):
    result = create_sourcegraph_mcp_server(settings_without_token)

    assert result is None
    assert "Sourcegraph token not configured" in caplog.text
    assert "proceeding without MCP server" in caplog.text


def test_create_sourcegraph_mcp_server_logs_warning_on_missing_token(
    settings_without_token, caplog
):
    import logging

    caplog.set_level(logging.WARNING)

    create_sourcegraph_mcp_server(settings_without_token)

    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "WARNING"
    assert "TRIAGE_SOURCEGRAPH_TOKEN" in caplog.records[0].message


def test_create_sourcegraph_mcp_server_config_structure(settings_with_token):
    result = create_sourcegraph_mcp_server(settings_with_token)

    server_config = result[MCP_SOURCEGRAPH_SERVER_NAME]

    assert "type" in server_config
    assert "url" in server_config
    assert "headers" in server_config

    assert isinstance(server_config["type"], str)
    assert isinstance(server_config["url"], str)
    assert isinstance(server_config["headers"], dict)


def test_create_sourcegraph_mcp_server_returns_dict_with_server_name_key(
    settings_with_token,
):
    result = create_sourcegraph_mcp_server(settings_with_token)

    assert isinstance(result, dict)
    assert len(result) == 1
    assert MCP_SOURCEGRAPH_SERVER_NAME in result


def test_create_sourcegraph_mcp_server_without_url_returns_none(
    settings_without_url, caplog
):
    result = create_sourcegraph_mcp_server(settings_without_url)

    assert result is None
    assert "Sourcegraph MCP URL not configured" in caplog.text
    assert "proceeding without MCP server" in caplog.text


def test_create_sourcegraph_mcp_server_requires_both_url_and_token(caplog):
    settings_no_token = Settings(
        sourcegraph_token=SecretStr(""),
        sourcegraph_mcp_url="https://sourcegraph.example.com/.api/mcp/v1",
    )
    settings_no_url = Settings(
        sourcegraph_token=SecretStr("test-token"), sourcegraph_mcp_url=""
    )

    result1 = create_sourcegraph_mcp_server(settings_no_token)
    result2 = create_sourcegraph_mcp_server(settings_no_url)

    assert result1 is None
    assert result2 is None
