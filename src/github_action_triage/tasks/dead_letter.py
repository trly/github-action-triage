import logging
from typing import Any

from github_action_triage.app.celery_app import app

logger = logging.getLogger(__name__)


@app.task(queue="dead_letter")
def send_to_dead_letter_queue(
    task_id: str,
    task_name: str,
    _args: list[Any],
    _kwargs: dict[str, Any],
    exception: str,
    traceback: str,
) -> None:
    logger.error(
        f"Message sent to dead letter queue: task_id={task_id}, task_name={task_name}, "
        f"exception={exception}, traceback={traceback}"
    )
