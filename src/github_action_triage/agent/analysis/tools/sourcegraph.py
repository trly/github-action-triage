import logging

from pydantic_ai.mcp import MCPServerStreamableHTTP

from github_action_triage.agent.config import Settings

logger = logging.getLogger(__name__)


def create_sourcegraph_toolset(settings: Settings) -> MCPServerStreamableHTTP | None:
    """Create and return Sourcegraph MCP toolset if configured.

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
        server = MCPServerStreamableHTTP(
            endpoint,
            headers={"Authorization": f"token {settings.sourcegraph_token.get_secret_value()}"},
        )
        logger.info("Sourcegraph: MCP server created successfully")
        return server
    except Exception as e:
        logger.warning(f"Failed to create Sourcegraph MCP server: {e}")
        return None
