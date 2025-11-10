import logging
from claude_agent_sdk.types import McpServerConfig
from github_action_triage.agent.config import Settings

logger = logging.getLogger(__name__)

MCP_SOURCEGRAPH_SERVER_NAME = "sourcegraph"


def create_sourcegraph_mcp_server(
    settings: Settings,
) -> dict[str, McpServerConfig] | None:
    if not settings.sourcegraph_token.get_secret_value():
        logger.warning(
            "Sourcegraph token not configured (TRIAGE_SOURCEGRAPH_TOKEN), proceeding without MCP server"
        )
        return None

    if not settings.sourcegraph_mcp_url:
        logger.warning(
            "Sourcegraph MCP URL not configured (TRIAGE_SOURCEGRAPH_MCP_URL), proceeding without MCP server"
        )
        return None

    try:
        server_config: McpServerConfig = {
            "type": "sse",
            "url": settings.sourcegraph_mcp_url,
            "headers": {
                "Authorization": f"token {settings.sourcegraph_token.get_secret_value()}"
            },
        }

        return {MCP_SOURCEGRAPH_SERVER_NAME: server_config}
    except Exception as e:
        logger.warning(f"Failed to create Sourcegraph MCP server: {
                       e}", exc_info=True)
        return None
