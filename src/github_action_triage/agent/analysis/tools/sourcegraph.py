import logging

from pydantic_ai.builtin_tools import MCPServerTool

from github_action_triage.agent.config import Settings

logger = logging.getLogger(__name__)


def create_sourcegraph_tool(settings: Settings) -> MCPServerTool | None:
    """Create and return Sourcegraph MCP builtin tool if configured.

    See: https://sourcegraph.com/docs/api/mcp#sourcegraph-mcp-server
    """
    if not settings.sourcegraph_token or settings.sourcegraph_token.get_secret_value() == "":
        logger.info("Sourcegraph: No access token configured")
        return None

    if not settings.sourcegraph_mcp_url:
        logger.info("Sourcegraph: No endpoint configured")
        return None

    # Ensure endpoint has MCP path
    endpoint = settings.sourcegraph_mcp_url
    if not endpoint.endswith("/.api/mcp/v1"):
        endpoint = endpoint.rstrip("/") + "/.api/mcp/v1"

    logger.info(f"Sourcegraph: Connecting to {endpoint}")

    try:
        tool = MCPServerTool(
            id="sourcegraph",
            url=endpoint,
            authorization_token=f"token {settings.sourcegraph_token.get_secret_value()}",
            description="Sourcegraph code search and analysis tools",
        )
        logger.info("Sourcegraph: MCP builtin tool created successfully")
        return tool
    except Exception as e:
        logger.warning(f"Failed to create Sourcegraph MCP tool: {e}")
        return None
