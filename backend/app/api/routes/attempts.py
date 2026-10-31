"""通用作答接口：上传录音立即返回 queued，轮询获取反馈。

POST /attempts      上传音频（multipart），任何题型（PRD 附录 A）
GET  /attempts/{id} 轮询转写与分数
"""

import logging
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, Session, SQLModel, col, select

from app.api.deps import (
    CurrentUser,
    OptionalCurrentUser,
    ScoringSubmitter,
    SessionDep,
    TeacherUserDep,
)
from app.core.config import settings
from app.core.ratelimit import SlidingWindowLimiter
from app.core.storage import AUDIO_SUFFIX_TO_MIME as _AUDIO_MIME_BY_SUFFIX
from app.core.storage import mime_to_suffix as storage_mime_to_suffix
from app.core.storage import save_audio_file
from app.crud import create_attempt, get_attempt
from app.models import (
    Attempt,
    AttemptItemType,
    AttemptPublic,
    AttemptStatus,
    Classroom,
    ClassroomExercise,
    Passage,
    PracticeSession,
    RepeatSentence,
    ScenarioQuestion,
    Student,
    User,
)
from app.scoring.audio_convert import probe_audio
from app.services import exam as exam_service
from app.services import followups, reading
from app.services.audio_playback import playback_path

logger = logging.getLogger(__name__)

router = APIRouter(tags=["attempts"])


def _delete_unreferenced_audio(session: Session, path: Path) -> None:
    """上传补偿：只删除本次生成、没有任何持久记录引用的音频文件。

    先查 attempt.audio_path 引用再删——数据库已提交的录音（含评分投递
    失败待恢复的）一定有行引用，不会被误删。补偿失败只记日志不阻断
    原有异常路径。
    """
    referenced = session.exec(
        select(Attempt.id).where(Attempt.audio_path == str(path)).limit(1)
    ).first()
    if referenced is not None:
        return
    try:
        path.unlink(missing_ok=True)
        logger.info("compensated orphan audio after failed attempt create: %s", path)
    except OSError:
        logger.warning("failed to compensate orphan audio %s", path)


# PRD US-02：短于 1 秒不打分，提示再录
MIN_DURATION_S = 1.0
# 作答提交限流（付费评分链路）：学生按人 / 匿名按 IP，各 60 次 / 5 分钟
_attempt_user_limiter = SlidingWindowLimiter(limit=60, window_s=300)
_attempt_ip_limiter = SlidingWindowLimiter(limit=60, window_s=300)
# 队列容量上限：超过时前端保留录音并提示稍后重试
MAX_QUEUE_SIZE = 200
# 分段读取的块大小（限量读取，避免整文件无上限进内存）
_CHUNK_SIZE = 64 * 1024
# 时长容差：客户端上报时长与探测时长偏差超过该值视为不可信
DURATION_TOLERANCE_S = 3.0


def _snapshot_attempt_item(
    session: Session,
    item_type: str,
    item_id: uuid.UUID,
    session_id: uuid.UUID | None,
) -> dict[str, object]:
    """复制提交时题目内容，评分时不读取后来被编辑的题库。"""
    if item_type not in {
        AttemptItemType.PASSAGE,
        AttemptItemType.REPEAT,
        AttemptItemType.QUESTION,
    }:
        raise HTTPException(status_code=422, detail="item_type 无效")
    if session_id is not None:
        practice_session = session.get(PracticeSession, session_id)
        if practice_session is not None and practice_session.assignment_id is not None:
            exercise = session.get(ClassroomExercise, practice_session.assignment_id)
            if exercise is not None:
                for item in exercise.snapshot_items:
                    if item.get("type") == item_type and str(item.get("id")) == str(
                        item_id
                    ):
                        return item
            # 换题授权：学生点「换一题」时绑定的**完整快照**（换题时刻内容，
            # 含考试字段）视同并入本会话题单——老师此后改题干/话题卡或删题，
            # 评分与学生所见保持一致（不再从实时题库重建）
            for exchanged in practice_session.exchanged_items or []:
                if exchanged.get("type") == item_type and str(
                    exchanged.get("id")
                ) == str(item_id):
                    return exchanged
            raise HTTPException(status_code=422, detail="题目不在本次发布练习内")

    if item_type == AttemptItemType.PASSAGE:
        item = session.get(Passage, item_id)
        if item is None:
            # 非发布会话（单元指派/自主练习）的逐句条目是合成 ID：
            # 对拆分中的活动篇目重做展开按 ID 匹配
            sentence_item = reading.find_reading_item_by_id(session, item_id)
            if sentence_item is not None:
                return sentence_item
            raise HTTPException(status_code=404, detail="题目不存在")
        return {
            "type": item_type,
            "id": str(item.id),
            "text": item.text,
            "suggested_seconds": item.suggested_seconds,
        }
    if item_type == AttemptItemType.REPEAT:
        item = session.get(RepeatSentence, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="题目不存在")
        return {
            "type": item_type,
            "id": str(item.id),
            "text": item.text,
            "suggested_seconds": item.suggested_seconds,
            # 分级题型字段（批次10）：与发布快照同构，评分语境不因非发布而缺失
            "exam_kind": item.exam_kind,
            "exam_level": item.exam_level,
        }
    item = session.get(ScenarioQuestion, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return {
        "type": item_type,
        "id": str(item.id),
        "text": item.text,
        "band": item.band,
        "suggested_seconds": item.suggested_seconds,
        # 分级题型字段（批次10）：与发布快照同构；话题卡要点参与评分
        "exam_kind": item.exam_kind,
        "exam_level": item.exam_level,
        "cue_card_bullets": item.cue_card_bullets,
        "prep_seconds": item.prep_seconds,
    }


def _resolve_submit_student(
    session: Session, session_id: uuid.UUID | None, current_user: User | None
) -> Student | None:
    """课堂作答归属解析：有 session 必须是登录学生本人；无 session 为匿名演示。

    返回归属的 Student 档案（演示作答返回 None）。
    """
    if session_id is None:
        # 公开练习页的整篇跟读演示：无归属主体。
        # 仅本地环境开放：生产匿名提交会真实触发付费评分、占用全站队列并落盘音频，
        # 与 demo 登录的 ENVIRONMENT 门禁保持一致（该演示页已下线，正常学生流程必带 session）
        if settings.ENVIRONMENT != "local":
            if current_user is None:
                raise HTTPException(
                    status_code=403, detail="演示提交未开放，请登录后使用"
                )
            raise HTTPException(
                status_code=422, detail="缺少练习会话，请刷新页面后重试"
            )
        return None
    if current_user is None:
        raise HTTPException(status_code=401, detail="请先登录后再提交课堂作答")
    if current_user.role != "student" and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="该操作仅限学生账号")
    practice_session = session.get(PracticeSession, session_id)
    if practice_session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    student = session.exec(
        select(Student).where(
            Student.classroom_id == practice_session.classroom_id,  # type: ignore[arg-type]
            Student.user_id == current_user.id,  # type: ignore[arg-type]
        )
    ).first()
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    if practice_session.student_id != student.id:
        raise HTTPException(status_code=403, detail="没有权限：该练习轮不属于你本人")
    return student


def _require_attempt_access(
    session: Session,
    attempt: Attempt,
    current_user: User | None,
) -> None:
    """音频/作答访问：本人学生（登录账号比对）或授权教师（管理员）可访问。"""
    if attempt.student_id is None:
        # 匿名演示作答（公开练习页）：没有归属主体可保护，按随机 UUID 回放
        return
    if current_user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    student = session.get(Student, attempt.student_id)
    if (
        student is not None
        and student.user_id == current_user.id
        and current_user.role == "student"
    ):
        return
    # 教师/管理员通道
    if current_user.role == "admin":
        return
    if student is not None:
        classroom = session.get(Classroom, student.classroom_id)
        if classroom is not None and classroom.owner_id == current_user.id:
            return
    raise HTTPException(
        status_code=403, detail="没有权限：您不是该作答所属课堂的授权教师"
    )


def _feedback_masked_for_user(
    session: Session, attempt: Attempt, current_user: User | None
) -> bool:
    """模考进行中，学生本人只能拿到回执与状态；授权教师/管理员与普通练习不受影响。"""
    if current_user is None or current_user.role != "student":
        return False
    if attempt.session_id is None:
        return False
    practice_session = session.get(PracticeSession, attempt.session_id)
    if practice_session is None or practice_session.assignment_id is None:
        return False
    exercise = session.get(ClassroomExercise, practice_session.assignment_id)
    return exam_service.exam_feedback_locked(session, practice_session, exercise)


def _snapshot_text(snapshot: dict[str, object], key: str) -> str | None:
    """快照文本字段提取：非空字符串才返回（题干投影用）。"""
    value = snapshot.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _attempt_public(
    attempt: Attempt, *, feedback_masked: bool = False
) -> AttemptPublic:
    """响应投影（不改 ORM）：遮罩时抹掉分数/转写/建议/词汇/rubric/错误详情。

    幂等重放、并发兜底、GET 轮询、上传回执共用同一投影，考试终结后
    feedback_masked=False，反馈完整恢复。题干（item_title/item_text）来自
    提交时快照：题库此后被编辑/删除不影响展示，也不属于遮罩范围
    （考试中学生本来就看得见题目）。
    """
    public = AttemptPublic.model_validate(attempt)
    snapshot = (
        attempt.item_snapshot if isinstance(attempt.item_snapshot, dict) else None
    )
    if snapshot is not None:
        public.item_title = _snapshot_text(snapshot, "title")
        public.item_text = _snapshot_text(snapshot, "text")
    if feedback_masked:
        public.transcript = None
        public.completeness = None
        public.fluency = None
        public.accuracy = None
        public.overall = None
        public.advice = None
        public.vocab = None
        public.rubric = None
        public.word_alignment = None
        public.teacher_review_tags = None
        public.teacher_feedback = None
        public.teacher_focus = False
        public.teacher_feedback_author = None
        public.teacher_feedback_at = None
        public.teacher_feedback_revision = 0
        public.error = None
    return public


def _idempotent_existing(
    session: Session,
    idempotency_key: str,
    item_type: str,
    item_id: uuid.UUID,
    session_id: uuid.UUID | None,
) -> Attempt | None:
    """按幂等键取已有作答；键指向别的题目/会话时直接拒绝。

    幂等键标识「一次录音」，客户端为每次录音独立生成且草稿把
    sessionId/itemType/itemId/key 绑定存储——键命中却对不上当前
    (题型, 题目, 会话)，只可能是客户端缺陷或构造请求（不同题型的同 UUID
    也不是同一题）。该键在库中已指向别的作答，既不能再存（撞全局唯一
    索引），更不能把那份回执当成这次的结果返回（串题）。
    """
    existing = session.exec(
        select(Attempt).where(Attempt.idempotency_key == idempotency_key)
    ).first()
    if existing is None:
        return None
    if (
        existing.item_type != item_type
        or existing.item_id != item_id
        or existing.session_id != session_id
    ):
        raise HTTPException(status_code=422, detail="作答凭证已失效，请重新录音后提交")
    return existing


@router.post("/attempts", response_model=AttemptPublic)
def create_attempt_upload(
    session: SessionDep,
    submitter: ScoringSubmitter,
    request: Request,
    current_user: OptionalCurrentUser = None,
    audio: UploadFile = File(..., description="浏览器 MediaRecorder 录制的音频"),
    item_type: str = Form(...),
    item_id: uuid.UUID = Form(...),
    duration_s: float = Form(..., gt=0, description="录音时长（秒）"),
    session_id: uuid.UUID | None = Form(default=None),
    idempotency_key: str | None = Form(
        default=None, max_length=64, description="幂等键：重传不重复创建"
    ),
) -> Any:
    """
    上传一条作答。立即返回 queued，分数通过轮询获取（PRD 不可协商 #4）。

    传 idempotency_key 时：已有同键作答直接返回（重传/断网重试不重复扣费）。
    队列繁忙时返回 503，前端保留录音提示稍后重试。
    音频真实格式/音轨/时长用 ffprobe 校验，不信客户端上报值。
    """
    # 归属解析：课堂作答（有 session）必须登录学生本人，演示作答无归属
    student = _resolve_submit_student(session, session_id, current_user)

    # 幂等检查：同键已有作答直接返回（同样校验归属，防越权读取他人作答）；
    # 键指向别的题目/会话时拒绝（防串题回执，见 _idempotent_existing）
    if idempotency_key:
        existing = _idempotent_existing(
            session, idempotency_key, item_type, item_id, session_id
        )
        if existing is not None:
            _require_attempt_access(session, existing, current_user)
            session.refresh(existing)
            return _attempt_public(
                existing,
                feedback_masked=_feedback_masked_for_user(
                    session, existing, current_user
                ),
            )

    # 限流（评分是付费链路：每次提交 = 一次 ASR 转写）：学生按人、其余按
    # IP。放在幂等重放之后——断网重传同键不占配额。60 次/5 分钟对正常
    # 作答节奏（录音 ≥3 秒 + 上传 + 轮询）极宽松，只挡脚本刷接口
    if student is not None:
        _attempt_user_limiter.check(f"student:{student.id}")
    else:
        _attempt_ip_limiter.check(
            f"ip:{request.client.host if request.client else 'unknown'}"
        )

    # 模考门禁：整场限时（服务端强约束）+ 每题一次作答。
    # 放在幂等检查之后：同一次录音断网重试（同幂等键）不受影响
    exam_one_attempt = False
    exam_assignment_id: uuid.UUID | None = None
    if session_id is not None:
        exam_session = session.get(PracticeSession, session_id)
        if exam_session is not None and student is not None:
            followups.check_session_open(session, exam_session, student)
        if exam_session is not None and exam_session.assignment_id is not None:
            bound_exercise = session.get(ClassroomExercise, exam_session.assignment_id)
            if bound_exercise is not None and bound_exercise.is_exam:
                # 预检阶段串行化：锁内在锁外各查一次幂等/每题一次，快速
                # 拦掉大多数重复；事务边界① 即释放。并发封口以边界②后的
                # 「锁内复查 + 插入」新短事务为准（毫秒级临界区）
                session.refresh(exam_session, with_for_update=True)
                if idempotency_key:
                    existing = _idempotent_existing(
                        session, idempotency_key, item_type, item_id, session_id
                    )
                    if existing is not None:
                        _require_attempt_access(session, existing, current_user)
                        return _attempt_public(
                            existing,
                            feedback_masked=_feedback_masked_for_user(
                                session, existing, current_user
                            ),
                        )
                already = session.exec(
                    select(Attempt.id).where(
                        Attempt.session_id == session_id,  # type: ignore[arg-type]
                        Attempt.item_id == item_id,
                    )
                ).first()
                if already is not None:
                    raise HTTPException(
                        status_code=422, detail="考试中每题只能作答一次"
                    )
                exam_service.require_exam_open(session, exam_session, bound_exercise)
                exam_service.require_current_item(
                    session, exam_session, bound_exercise, item_type, item_id
                )
                exam_one_attempt = True
                exam_assignment_id = exam_session.assignment_id

    # 事务边界①：门禁与临界区判断全部完成——立即提交，释放考试会话行锁
    # 与连接。后续读 body / ffprobe（可达 15 秒）/落盘不得占用连接：40 人
    # 自动考试同步上传时池上限 30 会被打穿，且 /today 每秒轮询的 settle
    # 要争同一行锁。真正的并发封口是边界②之后「锁内复查 + 插入」的
    # 毫秒级新短事务（每题一次的判定在那里重做一遍）
    student_id = student.id if student is not None else None
    session.commit()

    item_snapshot = _snapshot_attempt_item(session, item_type, item_id, session_id)
    # 事务边界②：快照查询开启的只读事务到此为止——body 读取与 probe
    # 全程零事务零连接
    session.commit()

    if duration_s < MIN_DURATION_S:
        raise HTTPException(status_code=422, detail="录音太短（不足 1 秒），请再录一次")

    # 限量读取：分段读入并即时检查大小上限（bytearray 增量拼接，避免 O(n²)）
    max_bytes = settings.MAX_AUDIO_MB * 1024 * 1024
    data = bytearray()
    while True:
        chunk = audio.file.read(_CHUNK_SIZE)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413, detail=f"音频超过 {settings.MAX_AUDIO_MB}MB 上限"
            )
    if not data:
        raise HTTPException(status_code=422, detail="音频为空，请再录一次")
    audio_bytes = bytes(data)

    # 真实格式/音轨/时长校验：ffprobe，不信客户端上报值
    mime_type = audio.content_type or "audio/webm"
    base_mime = mime_type.split(";")[0].strip().lower()
    suffix = _mime_to_suffix(base_mime)
    probe = probe_audio(audio_bytes, suffix)
    if probe is None:
        raise HTTPException(status_code=422, detail="音频文件无效或损坏，请重新录音")
    if not probe.has_audio:
        raise HTTPException(status_code=422, detail="文件中没有音频音轨，请重新录音")
    if probe.channels is not None and probe.channels > 2:
        raise HTTPException(status_code=422, detail="音轨数异常，请重新录音")
    actual_duration = probe.duration_s
    if actual_duration is not None:
        if actual_duration < MIN_DURATION_S:
            raise HTTPException(
                status_code=422, detail="录音太短（不足 1 秒），请再录一次"
            )
        if abs(actual_duration - duration_s) > DURATION_TOLERANCE_S:
            # 时长明显不符：以探测值为准重算，避免被恶意上报值利用
            duration_s = actual_duration

    # 队列容量检查：繁忙时拒绝，前端保留录音提示稍后重试
    queued_count = session.exec(
        select(func.count(Attempt.id)).where(  # type: ignore
            Attempt.status == AttemptStatus.QUEUED
        )
    ).one()
    if queued_count >= MAX_QUEUE_SIZE:
        raise HTTPException(
            status_code=503,
            detail="评分队列繁忙，请稍后重试",
        )

    # 事务边界③：队列计数的只读事务结束，落盘在事务外（本地磁盘写也
    # 不占连接）
    session.commit()
    audio_path = save_audio_file(audio_bytes, mime_type)
    # 模考同题并发兜底：上面的 already 检查是 check-then-insert，双击/断网重试
    # 并发时两个请求都能通过预检查。对考试会话行加锁后复查——锁只包住
    # 「复查 + 插入」的毫秒级临界区（音频校验在锁外），第二个请求在锁内
    # 看到首个作答后 422，不会产生双份作答/双倍评分费
    # 上传补偿（批次06）：落盘成功但持久化失败（考试门禁/幂等并发撞唯一
    # 约束/数据库故障）时，本次写入的文件没有任何记录引用——补偿删除，
    # 不留不受 TTL 管理的孤儿。数据库已提交的录音不在补偿范围（被行引用，
    # _delete_unreferenced_audio 会放行），评分投递失败由恢复机制接手
    try:
        if session_id is not None and student is not None:
            ps = session.get(PracticeSession, session_id)
            if ps is not None and ps.mode == followups.FOLLOWUP:
                task = session.get(ClassroomExercise, ps.assignment_id)
                if task is not None:
                    session.refresh(task, with_for_update=True)
                followups.check_session_open(session, ps, student)
        if exam_one_attempt and session_id is not None:
            # 新短事务：先取发布快照（无锁读），再锁会话行做毫秒级
            # 「复查 + 插入」临界区
            bound_exercise = session.get(ClassroomExercise, exam_assignment_id)
            locked_session = session.exec(
                select(PracticeSession)
                .where(PracticeSession.id == session_id)
                .with_for_update()
            ).first()
            if locked_session is not None and bound_exercise is not None:
                # 锁内复查整场截止：音频校验（probe 可达秒级）期间可能跨过
                # 截止，与预检查同一口径再判一次；纯时间判定不 commit，
                # 不释放本临界区行锁
                exam_service.require_deadline_not_passed(locked_session, bound_exercise)
                already = session.exec(
                    select(Attempt.id).where(
                        Attempt.session_id == session_id,  # type: ignore[arg-type]
                        Attempt.item_id == item_id,
                    )
                ).first()
                if already is not None:
                    raise HTTPException(
                        status_code=422, detail="考试中每题只能作答一次"
                    )
        attempt = Attempt(
            item_type=item_type,
            item_id=item_id,
            student_id=student_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
            item_snapshot=item_snapshot,
            audio_path=str(audio_path),
            audio_mime=mime_type,
            duration_s=duration_s,
            engine=settings.SCORING_PROVIDER,
        )
        attempt = create_attempt(session=session, attempt_in=attempt)
    except IntegrityError as exc:
        session.rollback()
        if idempotency_key and "idempotency_key" in str(exc.orig):
            try:
                existing = _idempotent_existing(
                    session, idempotency_key, item_type, item_id, session_id
                )
            except HTTPException:
                # 键指向别的题目/会话：新作答存不进（全局唯一键）、旧回执不能
                # 返回（串题）——补偿删除本次文件后按稳定 422 拒绝
                _delete_unreferenced_audio(session, audio_path)
                raise
            if existing is not None:
                # 兜底分支同样校验归属，封死「预检查时未提交→撞唯一约束→拿到他人作答」路径
                _require_attempt_access(session, existing, current_user)
                _delete_unreferenced_audio(session, audio_path)
                return _attempt_public(
                    existing,
                    feedback_masked=_feedback_masked_for_user(
                        session, existing, current_user
                    ),
                )
        _delete_unreferenced_audio(session, audio_path)
        raise
    except Exception:
        # 数据库异常后连接可能处于 aborted 态：先 rollback 复位，否则
        # 补偿查询本身也会失败（返修E）。补偿全程受保护——补偿失败宁可
        # 保留文件交给孤儿扫描，也不掩盖原始异常或误删已入库音频
        try:
            session.rollback()
        except Exception:  # noqa: BLE001 - 复位失败只能保留文件并记录
            logger.warning(
                "rollback before audio compensation failed for %s", audio_path
            )
        try:
            _delete_unreferenced_audio(session, audio_path)
        except Exception:  # noqa: BLE001 - 补偿不得掩盖原始异常
            logger.warning(
                "audio compensation failed; keep %s for orphan scan", audio_path
            )
        raise

    submitter(attempt.id)
    session.refresh(attempt)
    return _attempt_public(
        attempt,
        feedback_masked=_feedback_masked_for_user(session, attempt, current_user),
    )


def _mime_to_suffix(base_mime: str) -> str:
    # 唯一事实源在 app.core.storage（与落盘/回放共用，见该处注释）
    return storage_mime_to_suffix(base_mime)


class AttemptBatchRead(SQLModel):
    attempt_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)

    @field_validator("attempt_ids")
    @classmethod
    def _deduplicate_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        # Validate the raw length first, then preserve first-occurrence order.
        return list(dict.fromkeys(value))


# Keep static paths ahead of /attempts/{attempt_id}.
@router.post("/attempts/batch-read", response_model=list[AttemptPublic])
def read_attempts_batch(
    session: SessionDep,
    body: AttemptBatchRead,
    current_user: TeacherUserDep,
) -> list[AttemptPublic]:
    """Read up to 100 attempts in request order after authorizing the entire batch."""
    attempts = session.exec(
        select(Attempt).where(col(Attempt.id).in_(body.attempt_ids))
    ).all()
    by_id = {attempt.id: attempt for attempt in attempts}
    if len(by_id) != len(body.attempt_ids):
        raise HTTPException(status_code=404, detail="Attempt not found")

    if current_user.role != "admin":
        student_ids = {
            attempt.student_id for attempt in attempts if attempt.student_id is not None
        }
        if student_ids:
            # Authorize the whole batch without per-attempt ownership queries.
            authorized_ids = set(
                session.exec(
                    select(Student.id)
                    .join(Classroom, col(Student.classroom_id) == Classroom.id)
                    .where(
                        col(Student.id).in_(student_ids),
                        Classroom.owner_id == current_user.id,
                    )
                ).all()
            )
            if student_ids != authorized_ids:
                raise HTTPException(
                    status_code=403,
                    detail="没有权限：您不是该作答所属课堂的授权教师",
                )

    # No projection or partial result is exposed until all access checks pass.
    return [
        _attempt_public(
            by_id[attempt_id],
            feedback_masked=_feedback_masked_for_user(
                session, by_id[attempt_id], current_user
            ),
        )
        for attempt_id in body.attempt_ids
    ]


@router.get("/attempts/{attempt_id}", response_model=AttemptPublic)
def read_attempt(
    session: SessionDep,
    attempt_id: uuid.UUID,
    current_user: OptionalCurrentUser = None,
) -> Any:
    """轮询作答状态与反馈。done 返回转写和分数，failed 返回 error。

    需要本人学生凭证或授权教师身份。
    """
    attempt = get_attempt(session=session, attempt_id=attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    _require_attempt_access(session, attempt, current_user)
    return _attempt_public(
        attempt,
        feedback_masked=_feedback_masked_for_user(session, attempt, current_user),
    )


@router.get("/attempts/{attempt_id}/comparison", response_model=list[AttemptPublic])
def read_attempt_comparison(
    session: SessionDep,
    attempt_id: uuid.UUID,
    current_user: CurrentUser,
) -> list[AttemptPublic]:
    attempt = session.get(Attempt, attempt_id)
    if attempt is None or attempt.session_id is None:
        raise HTTPException(404, detail="Attempt not found")
    _require_attempt_access(session, attempt, current_user)
    ps = session.get(PracticeSession, attempt.session_id)
    exercise = (
        session.get(ClassroomExercise, ps.assignment_id)
        if ps and ps.assignment_id
        else None
    )
    if exercise is not None and exercise.is_exam:
        raise HTTPException(403, detail="Practice comparison unavailable for exams")
    base = select(Attempt).where(
        Attempt.session_id == attempt.session_id,
        Attempt.student_id == attempt.student_id,
        Attempt.item_id == attempt.item_id,
        Attempt.item_type == attempt.item_type,
        Attempt.status == "done",
    )
    first = session.exec(
        base.order_by(col(Attempt.created_at), col(Attempt.id)).limit(1)
    ).first()
    latest = session.exec(
        base.order_by(col(Attempt.created_at).desc(), col(Attempt.id).desc()).limit(1)
    ).first()
    if first is None or latest is None or first.id == latest.id:
        return []
    return [_attempt_public(first), _attempt_public(latest)]


class TeacherFeedbackWrite(SQLModel):
    review_tags: (
        list[Literal["transcript_error", "advice_unsuitable", "reviewed"]] | None
    ) = Field(default=None, max_length=3)
    text: str = Field(max_length=4000)
    focus: bool = False
    expected_revision: int = Field(ge=0)


@router.put("/attempts/{attempt_id}/teacher-feedback", response_model=AttemptPublic)
def write_teacher_feedback(
    session: SessionDep,
    attempt_id: uuid.UUID,
    body: TeacherFeedbackWrite,
    current_user: CurrentUser,
) -> AttemptPublic:
    from app.crud import update_teacher_feedback

    attempt = session.get(Attempt, attempt_id)
    if attempt is None or attempt.student_id is None:
        raise HTTPException(404, detail="Attempt not found")
    if current_user.role == "student":
        raise HTTPException(403, detail="Teacher access required")
    _require_attempt_access(session, attempt, current_user)
    update_teacher_feedback(
        session,
        attempt,
        text=body.text,
        focus=body.focus,
        review_tags=list(body.review_tags) if body.review_tags is not None else None,
        author=current_user.full_name or current_user.email or "Teacher",
        expected_revision=body.expected_revision,
    )
    return _attempt_public(attempt)


@router.get("/attempts/{attempt_id}/audio")
def read_attempt_audio(
    session: SessionDep,
    attempt_id: uuid.UUID,
    current_user: OptionalCurrentUser = None,
) -> FileResponse:
    """回放一条作答的音频。本人学生或授权教师可访问，不靠 UUID 难猜。"""
    attempt = get_attempt(session=session, attempt_id=attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    _require_attempt_access(session, attempt, current_user)
    path = Path(attempt.audio_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio not found")
    path = playback_path(path)
    safe_mime = _AUDIO_MIME_BY_SUFFIX.get(path.suffix, "application/octet-stream")
    # 作答录音不可变：显式允许浏览器缓存一天（讲评反复回放/学生回听不再
    # 整段重传）。private——响应按人授权，共享代理不得存储
    return FileResponse(
        path,
        media_type=safe_mime,
        headers={"Cache-Control": "private, max-age=86400"},
    )
