"""作答音频保留期（TTL）清理：磁盘容量兜底，不动评分结果。

审计估算录音无上限增长约 40–140GB/年（2026-10-07）；评分产物（转写/
分数/建议）都在数据库里，音频本体过期后只剩回放价值。AUDIO_TTL_DAYS=0
（默认）完全关闭本模块——上线开关只是一个环境变量，不改代码。

只删作答音频（AUDIO_STORAGE_DIR 根下的 uuid 文件）；content/ 子目录是
内容标准音/TTS 缓存，小且必需，永不触碰。只清终态作答（done/failed），
排队/评分中的音频仍被 worker 使用。文件删除后回放端点按文件缺失 404，
前端回放按钮报错即可，无契约变化。

推进语义（批次06）：候选 = 终态 + 超过保留期 + audio_purged_at IS NULL，
按 (created_at, id) 稳定排序、每轮至多 PURGE_BATCH_LIMIT 行。处理完成
（删除或结算）即落标记，后续轮次推进到下一批——此前没有标记，候选超过
单轮上限后会永远重复选中同一批已删记录。删除失败（OSError）不标记，
下轮重试；文件本就缺失/路径越界/指向 content 的行结算标记但不计删除数，
不长期阻塞其它候选。
"""

import logging
import threading
from datetime import timedelta
from pathlib import Path

from sqlalchemy import update
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import Attempt, AttemptStatus

logger = logging.getLogger(__name__)

# 单轮清理上限：一次线程迭代删除过多文件会长时间占住磁盘 IO
PURGE_BATCH_LIMIT = 500
RETENTION_INTERVAL_S = 24 * 3600


def purge_expired_attempt_audio(session: Session) -> int:
    """删除超过保留期的终态作答音频文件，返回本轮删除的文件数。

    TTL=0 直接返回；处理完成的行写 audio_purged_at（删除、文件缺失、
    越界/content 结算都算完成），失败行留待下轮重试。
    """
    ttl_days = settings.AUDIO_TTL_DAYS
    if ttl_days <= 0:
        return 0
    storage = Path(settings.AUDIO_STORAGE_DIR).resolve()
    content_dir = storage / "content"
    from app.models import get_datetime_utc

    cutoff = get_datetime_utc() - timedelta(days=ttl_days)
    rows = session.exec(
        select(Attempt.id, Attempt.audio_path)
        .where(
            col(Attempt.status).in_([AttemptStatus.DONE, AttemptStatus.FAILED]),
            col(Attempt.created_at) < cutoff,
            col(Attempt.audio_purged_at).is_(None),
        )
        .order_by(col(Attempt.created_at), col(Attempt.id))
        .limit(PURGE_BATCH_LIMIT)
    ).all()
    purged = 0
    settled_ids: list[object] = []
    for attempt_id, audio_path in rows:
        if not audio_path:
            # 模型上非空，防御性结算（无文件可管）
            settled_ids.append(attempt_id)
            continue
        path = Path(audio_path).resolve()
        # 路径护栏：只管理存储根下的**直接**文件（uuid 音频平铺在根上）。
        # content/ 标准音、其它子目录、存储根之外的路径都不是本模块该删的
        # 文件——一律结算标记（不删任何东西），不再每轮重复选中阻塞推进
        if path.parent != storage:
            if content_dir == path or content_dir in path.parents:
                logger.warning(
                    "settle audio path pointing into content dir: %s", audio_path
                )
            elif storage not in path.parents:
                logger.warning("settle audio outside storage dir: %s", audio_path)
            else:
                logger.warning(
                    "settle audio in unexpected subdirectory: %s", audio_path
                )
            settled_ids.append(attempt_id)
            continue
        try:
            existed = path.exists()
            if existed:
                path.unlink()
        except OSError:
            # 删除失败不标记：下一轮重试；已删/缺失之外的异常不吞进度
            logger.exception("failed to delete audio %s", audio_path)
            continue
        if existed:
            purged += 1
        # 文件原本缺失 → 结算为已清理（不再有可管理的文件）
        settled_ids.append(attempt_id)
    if settled_ids:
        session.execute(  # ty: ignore[deprecated] - exec() 不接受 update 语句
            update(Attempt)
            .where(col(Attempt.id).in_(settled_ids))
            .values(audio_purged_at=get_datetime_utc())
        )
        session.commit()
    if purged:
        logger.info(
            "audio retention purged %d files, settled %d rows (ttl=%dd)",
            purged,
            len(settled_ids),
            ttl_days,
        )
    return purged


_retention_stop: threading.Event | None = None
_retention_thread: threading.Thread | None = None


def _retention_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(RETENTION_INTERVAL_S):
        # 引擎每轮重新解析：与 scoring sweeper 同一模式，测试覆盖同样生效
        from app.core.db import engine

        try:
            with Session(engine) as session:
                purge_expired_attempt_audio(session)
        except Exception:  # noqa: BLE001 - 清理是兜底，失败只记日志不能带崩线程
            logger.exception("audio retention iteration failed")


def start_audio_retention() -> None:
    """启动每日清理线程（main lifespan 调用；TestClient 不进 lifespan 故测试不受影响）。"""
    global _retention_stop, _retention_thread
    if _retention_thread is not None and _retention_thread.is_alive():
        return
    _retention_stop = threading.Event()
    _retention_thread = threading.Thread(
        target=_retention_loop,
        args=(_retention_stop,),
        name="audio-retention",
        daemon=True,
    )
    _retention_thread.start()


def stop_audio_retention() -> None:
    global _retention_stop, _retention_thread
    if _retention_stop is not None:
        _retention_stop.set()
    _retention_stop = None
    _retention_thread = None
