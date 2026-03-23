"""Sourcegraph Deep Search client for CI failure analysis."""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DeepSearchError(Exception):
    """Raised when Deep Search fails or returns an error state."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DeepSearchResult:
    """Result from a completed Deep Search conversation."""

    conversation_name: str
    conversation_url: str
    answer_markdown: str
    poll_count: int
    elapsed_seconds: float


def _determine_state(state: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """Determine conversation state from the state object.

    The API uses a oneOf discriminator — the state is whichever key is present.
    """
    for key in ("completed", "error", "canceled", "processing"):
        if key in state:
            return key, state.get(key)
    return "unknown", None


async def run_deep_search(
    sourcegraph_url: str,
    token: str,
    question: str,
    timeout_seconds: int = 300,
    poll_interval_seconds: float = 3.0,
) -> DeepSearchResult:
    """Run a Deep Search conversation and poll until completion.

    Args:
        sourcegraph_url: Base URL of the Sourcegraph instance.
        token: Sourcegraph access token.
        question: The analysis question (max 100,000 chars).
        timeout_seconds: Maximum time to wait for completion.
        poll_interval_seconds: Interval between poll requests.

    Returns:
        DeepSearchResult with the answer markdown and telemetry.

    Raises:
        DeepSearchError: If the conversation fails, is canceled, or times out.
    """
    base_url = sourcegraph_url.rstrip("/")
    headers = {
        "Authorization": f"token {token}",
        "Connect-Protocol-Version": "1",
        "Content-Type": "application/json",
    }

    create_body = {
        "conversation": {
            "questions": [{"input": [{"question": {"text": question}}]}]
        }
    }

    start_time = time.monotonic()

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Create conversation
        create_response = await client.post(
            f"{base_url}/api/deepsearch.v1.Service/CreateConversation",
            headers=headers,
            json=create_body,
        )
        create_response.raise_for_status()
        conversation = create_response.json()

        conversation_name = conversation.get("name", "")
        conversation_url = conversation.get("url", "")

        logger.info(
            f"Deep Search conversation created: {conversation_name} ({conversation_url})"
        )

        # Poll for completion
        poll_count = 0
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= timeout_seconds:
                raise DeepSearchError(
                    f"Deep Search timed out after {elapsed:.1f}s ({poll_count} polls)",
                    code="TIMEOUT",
                )

            state_obj = conversation.get("state", {})
            state_key, state_data = _determine_state(state_obj)

            if state_key == "completed":
                elapsed_final = time.monotonic() - start_time
                questions = conversation.get("questions", [])
                answer_markdown = ""
                if questions:
                    answers = questions[0].get("answer", [])
                    if answers:
                        markdown_obj = answers[0].get("markdown", {})
                        answer_markdown = markdown_obj.get("text", "")

                logger.info(
                    f"Deep Search completed: {conversation_name} "
                    f"({poll_count} polls, {elapsed_final:.1f}s)"
                )

                return DeepSearchResult(
                    conversation_name=conversation_name,
                    conversation_url=conversation_url,
                    answer_markdown=answer_markdown,
                    poll_count=poll_count,
                    elapsed_seconds=elapsed_final,
                )

            if state_key == "error":
                error_code = state_data.get("code", "ERROR_UNSPECIFIED") if state_data else "ERROR_UNSPECIFIED"
                error_message = state_data.get("message", "Unknown error") if state_data else "Unknown error"
                raise DeepSearchError(
                    f"Deep Search failed: {error_message} (code={error_code})",
                    code=error_code,
                )

            if state_key == "canceled":
                raise DeepSearchError("Deep Search conversation was canceled", code="CANCELED")

            if state_key != "processing":
                raise DeepSearchError(
                    f"Deep Search returned unexpected state: {state_obj}",
                    code="UNKNOWN_STATE",
                )

            # Still processing — poll again
            poll_count += 1
            if poll_count % 10 == 0:
                logger.info(
                    f"Deep Search polling: {conversation_name} "
                    f"({poll_count} polls, {elapsed:.1f}s elapsed)"
                )

            await asyncio.sleep(poll_interval_seconds)

            poll_response = await client.post(
                f"{base_url}/api/deepsearch.v1.Service/GetConversation",
                headers=headers,
                json={"name": conversation_name},
            )
            poll_response.raise_for_status()
            conversation = poll_response.json()
