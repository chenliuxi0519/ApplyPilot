from fastapi import APIRouter

from app.api.routes import agent_chat, login, private, users, utils
from app.core.config import settings
from app.modules.agent_runs.router import router as agent_run_router
from app.modules.applications.router import router as application_router
from app.modules.applications.router import task_router as application_task_router
from app.modules.profiles.router import router as profile_router
from app.modules.programs.router import review_router as requirement_review_router
from app.modules.programs.router import router as program_router

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(profile_router)
api_router.include_router(program_router)
api_router.include_router(requirement_review_router)
api_router.include_router(application_router)
api_router.include_router(application_task_router)
api_router.include_router(agent_run_router)
api_router.include_router(agent_chat.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
