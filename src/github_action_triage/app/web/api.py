import logging
from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import JSONResponse
from githubkit.webhooks import parse
from githubkit.versions.latest.models import WebhookWorkflowJobCompleted
from github_action_triage.app.web.github_webhooks import (
    is_failure_workflow_job,
    log_workflow_job_failure,
    map_workflow_job_event,
)

router = APIRouter(prefix="/github", tags=["github"])
logger = logging.getLogger(__name__)


@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def handle_webhook(request: Request) -> JSONResponse:
    event_name = request.headers.get("X-GitHub-Event")
    if not event_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Event header",
        )

    body = await request.body()

    try:
        event = parse(event_name, body)
    except Exception as exc:
        logger.exception(f"Failed to parse {event_name} webhook")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid GitHub webhook payload",
        ) from exc

    if is_failure_workflow_job(event):
        log_workflow_job_failure(event)
        await handle_workflow_job_failure(request, event)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED, content={"status": "accepted"}
    )


async def handle_workflow_job_failure(
    request: Request, event: WebhookWorkflowJobCompleted
) -> None:
    logger.info("Starting failure analysis and remediation")

    # Map webhook event to domain event
    triage_event = map_workflow_job_event(event)
    
    # Get triage service from app state
    service = request.app.state.triage_service
    
    # Process the failure
    result = await service.handle_failure(triage_event)
    
    logger.info(
        "AI remediation result",
        extra={"triage_outcome": result.outcome.value, "result_message": result.message},
    )


@router.get("/health")
async def health_check():
    return {"status": "healthy"}

