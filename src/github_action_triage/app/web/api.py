import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from githubkit.webhooks import parse

from github_action_triage.app.web.github_webhooks import (
    is_failure_workflow_job,
    log_workflow_job_failure,
    map_workflow_job_event,
)
from github_action_triage.app.web.signature import verify_github_signature
from github_action_triage.tasks.triage import analyze_workflow_failure

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
        
        # Extract GitHub delivery ID for idempotency
        github_delivery_id = request.headers.get("X-GitHub-Delivery")
        if not github_delivery_id:
            logger.warning(
                f"Missing X-GitHub-Delivery header for {triage_event.repository.owner}/{triage_event.repository.name}"
            )
        
        # Fetch failure context
        context = await service._context_provider.fetch_failure_context(triage_event)
        
        # Enqueue Celery task
        task = analyze_workflow_failure.delay(
            context=context.model_dump(),
            github_delivery_id=github_delivery_id,
        )
        
        logger.info(
            f"Enqueued triage task: task_id={task.id}, delivery_id={github_delivery_id}, "
            f"repo={context.repository_full_name}"
        )
        
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"status": "accepted", "task_id": task.id},
        )

    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={"status": "accepted"})


@router.get("/health")
async def health_check():
    return {"status": "healthy"}
