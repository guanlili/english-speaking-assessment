from fastapi import APIRouter

from app.api.routes import (
    admin_composer,
    admin_content,
    admin_content_copy,
    admin_dashboard,
    admin_exam,
    admin_export,
    admin_question_io,
    attempts,
    audio,
    changelog,
    classes,
    exports,
    login,
    metrics,
    students,
    users,
    utils,
    vocab_ai,
    vocab_levels,
    vocabulary,
)

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(classes.router)
api_router.include_router(attempts.router)
api_router.include_router(exports.router)
api_router.include_router(students.router)
api_router.include_router(admin_content.router)
api_router.include_router(admin_content_copy.router)
api_router.include_router(admin_composer.router)
api_router.include_router(admin_dashboard.router)
api_router.include_router(admin_export.router)
api_router.include_router(admin_exam.router)
api_router.include_router(admin_question_io.router)
api_router.include_router(metrics.router)
api_router.include_router(audio.router)
api_router.include_router(vocabulary.router)
api_router.include_router(vocab_levels.router)
api_router.include_router(vocab_ai.router)
api_router.include_router(changelog.router)
