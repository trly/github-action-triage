import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import JSONResponse
from githubkit.webhooks import parse

from github_action_triage.app.web.github_webhooks import (
    is_failure_workflow_job,
    log_workflow_job_failure,
    map_workflow_job_event,
)
from github_action_triage.app.web.signature import verify_github_signature

router = APIRouter(prefix="/github", tags=["github"])
logger = logging.getLogger(__name__)


@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def handle_webhook(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    event_name = request.headers.get("X-GitHub-Event")
    if not event_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Event header",
        )

    body = await request.body()

    signature = request.headers.get("X-Hub-Signature-256", "")
    settings = request.app.state.settings

    if not verify_github_signature(body, signature, settings.github_webhook_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

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
        triage_event = map_workflow_job_event(event)
        service = request.app.state.triage_service
        background_tasks.add_task(service.process_failure_async, triage_event)

    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={"status": "accepted"})


@router.get("/health")
async def health_check():
    return {"status": "healthy"}
