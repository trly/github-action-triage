from celery import Celery

from github_action_triage.agent.config import get_settings

settings = get_settings()

app = Celery("github_action_triage")

app.conf.broker_url = settings.redis_url
app.conf.result_backend = settings.redis_url

app.conf.task_serializer = "json"
app.conf.result_serializer = "json"
app.conf.accept_content = ["json"]

app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True

app.conf.worker_prefetch_multiplier = 1

app.conf.result_expires = 3600

app.conf.timezone = "UTC"
app.conf.enable_utc = True

app.autodiscover_tasks(["github_action_triage.tasks"])
