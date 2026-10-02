from fastapi import APIRouter

from app.api.routes import (
    admin_content,
    attempts,
    audio,
    classes,
    login,
    students,
    users,
    utils,
    vocabulary,
)

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(classes.router)
api_router.include_router(attempts.router)
api_router.include_router(students.router)
api_router.include_router(admin_content.router)
api_router.include_router(audio.router)
api_router.include_router(vocabulary.router)
