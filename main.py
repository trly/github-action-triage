import logging

from github_action_triage.app.config.settings import get_settings
from github_action_triage.app.factory import create_app

# Configure logging once, globally, before creating app
settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(levelname)s:     %(name)s - %(message)s",
)

app = create_app()


if __name__ == "__main__":
    print("Starting server...")
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
