"""每日挑战接口（#618）：学生看今日 3 款 / 开挑战轮，教师只读参与情况。

口径：挑战轮独立 `kind="daily_challenge"` —— 不进教师任务统计、不影响
任务首答成绩；素材不足时降级并在响应里给出原因。
"""

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SessionDep, StudentUserDep
from app.api.routes.class_shared import (
    _get_classroom,
    _require_classroom_teacher,
    _student_profile_of,
)
from app.models import (
    VocabularyChallengeCreated,
    VocabularyChallengeParticipation,
    VocabularyDailyChallenge,
)
from app.services import vocab_challenge as service

router = APIRouter()


@router.get(
    "/classes/{code}/vocabulary/student/challenge",
    response_model=VocabularyDailyChallenge,
)
def read_daily_challenge(
    code: str, session: SessionDep, current_user: StudentUserDep
) -> VocabularyDailyChallenge:
    """今日挑战配置 + 完成状态（同一天同班恒定，可反复刷新）。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user, "vocabulary")
    day = service.challenge_day()
    pack = service.compose_pack(session, classroom.id, day)
    existing = service.todays_session(session, student.id, day)
    return VocabularyDailyChallenge.model_validate(
        service.challenge_payload(
            pack, classroom_code=classroom.code, vocab_session=existing
        )
    )


@router.post(
    "/classes/{code}/vocabulary/student/challenge/sessions",
    response_model=VocabularyChallengeCreated,
)
def start_daily_challenge(
    code: str, session: SessionDep, current_user: StudentUserDep
) -> VocabularyChallengeCreated:
    """开今日挑战轮；当日未完成的轮直接续做，不重复开。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user, "vocabulary")
    day = service.challenge_day()
    vocab_session = service.start_challenge(
        session, classroom_id=classroom.id, student_id=student.id, day=day
    )
    if vocab_session is None:
        raise HTTPException(
            status_code=409, detail="challenge_unavailable：今日素材不足，暂不能开挑战"
        )
    return VocabularyChallengeCreated(
        session_id=vocab_session.id,
        total_items=len(vocab_session.snapshot_items or []),
    )


@router.get(
    "/classes/{code}/vocabulary/challenge/participation",
    response_model=VocabularyChallengeParticipation,
)
def read_challenge_participation(
    code: str, session: SessionDep, current_user: CurrentUser
) -> VocabularyChallengeParticipation:
    """教师端只读参与情况（今天开过挑战 / 已完成的人数）。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user, "vocabulary")
    day = service.challenge_day()
    started, completed = service.class_participation(session, classroom.id, day)
    return VocabularyChallengeParticipation(
        date=day, started_count=started, completed_count=completed
    )
