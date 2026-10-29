"""口语原音频 ZIP。

只打包磁盘上的原始录音字节（不转码、不收入 `.playback.wav`）。
清单是 UTF-8 BOM 的 manifest.csv。全部缺失或没有作答时不产生空 ZIP。
"""

from __future__ import annotations

import csv
import io
import logging
import re
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.storage import mime_to_suffix
from app.models import (
    Attempt,
    AttemptStatus,
    Classroom,
    ClassroomExercise,
    ExportScope,
    PracticeSession,
    Student,
    User,
)

logger = logging.getLogger(__name__)

MANIFEST_COLUMNS = [
    "attempt_id",
    "student_id",
    "student_name",
    "student_no",
    "classroom_code",
    "classroom_name",
    "session_id",
    "exercise_id",
    "item_type",
    "item_id",
    "item_title",
    "created_at",
    "duration_s",
    "overall",
    "status",
    "audio_mime",
    "zip_path",
    "missing",
]

ITEM_TYPE_LABEL = {
    "passage": "文章朗读",
    "repeat": "听句复述",
    "question": "情景问答",
}

_ILLEGAL = re.compile(r"[\x00-\x1f\\/:*?\"<>|]+")


@dataclass
class ExportCandidate:
    attempt_id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    student_no: str
    classroom_code: str
    classroom_name: str
    session_id: uuid.UUID | None
    exercise_id: uuid.UUID | None
    exercise_title: str | None
    item_type: str
    item_id: uuid.UUID
    item_title: str
    created_at: datetime | None
    duration_s: float
    overall: int | None
    status: str
    audio_mime: str
    audio_path: str
    audio_purged_at: datetime | None


@dataclass
class BuildResult:
    error: str | None
    included: int
    missing: int
    byte_size: int
    artifact_name: str | None


def practice_zone() -> ZoneInfo:
    return ZoneInfo(settings.PRACTICE_TZ)


def to_shanghai(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(practice_zone())


def sanitize_component(value: str, fallback: str, limit: int = 40) -> str:
    """文件名片段：去掉路径分隔与控制字符，空则用 fallback。"""
    cleaned = _ILLEGAL.sub("_", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    cleaned = re.sub(r"_+", "_", cleaned)
    if not cleaned or cleaned in {".", ".."}:
        cleaned = fallback
    return cleaned[:limit].rstrip(" ._") or fallback


def export_directory() -> Path:
    directory = Path(settings.EXPORT_STORAGE_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def artifact_file(relpath: str | None) -> Path | None:
    if not relpath:
        return None
    name = Path(relpath).name
    if not name or name in {".", ".."}:
        return None
    return export_directory() / name


def is_playback_name(path: Path) -> bool:
    return path.name.lower().endswith(".playback.wav")


def present_source(candidate: ExportCandidate) -> Path | None:
    """可打进 ZIP 的原始文件。已清理、缺失、或本身是回放缓存则不算。"""
    if candidate.audio_purged_at is not None:
        return None
    path = Path(candidate.audio_path)
    try:
        if is_playback_name(path) or not path.is_file():
            return None
        return path
    except OSError:
        logger.warning("export stat failed for attempt %s", candidate.attempt_id)
        return None


def present_nbytes(candidates: list[ExportCandidate]) -> int:
    total = 0
    for candidate in candidates:
        source = present_source(candidate)
        if source is None:
            continue
        try:
            total += source.stat().st_size
        except OSError:
            logger.warning("export size failed for attempt %s", candidate.attempt_id)
    return total


def download_name_for(
    *,
    scope: str,
    classroom_name: str | None,
    exercise_title: str | None,
    start: datetime | None,
    end: datetime | None,
    now: datetime,
) -> str:
    stamp = to_shanghai(now).strftime("%Y%m%d-%H%M")
    if scope == ExportScope.SELF:
        root = f"BELP_我的录音_{stamp}"
    else:
        klass = sanitize_component(classroom_name or "课堂", "课堂", 24)
        if exercise_title:
            middle = sanitize_component(exercise_title, "练习", 24)
        elif start is not None and end is not None:
            middle = (
                f"{to_shanghai(start).strftime('%Y%m%d')}"
                f"-{to_shanghai(end).strftime('%Y%m%d')}"
            )
        else:
            middle = "录音"
        root = f"BELP_{klass}_{middle}_{stamp}"
    root = _ILLEGAL.sub("_", root).strip(" ._")
    if not root.startswith("BELP_"):
        root = f"BELP_{root}"
    return f"{root[:180]}.zip"


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _as_uuid(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def query_candidates(
    session: Session, filt: dict[str, object]
) -> list[ExportCandidate]:
    """按冻结的 filter 取出 done/failed 作答。queued/scoring 不进入清单。"""
    stmt = (
        select(Attempt, Student, User, Classroom, PracticeSession, ClassroomExercise)  # ty: ignore[no-matching-overload]
        .join(Student, col(Attempt.student_id) == Student.id)
        .outerjoin(User, col(Student.user_id) == User.id)
        .join(Classroom, col(Student.classroom_id) == Classroom.id)
        .outerjoin(PracticeSession, col(Attempt.session_id) == PracticeSession.id)
        .outerjoin(
            ClassroomExercise,
            col(PracticeSession.assignment_id) == ClassroomExercise.id,
        )
        .where(col(Attempt.status).in_([AttemptStatus.DONE, AttemptStatus.FAILED]))
    )
    scope = filt.get("scope")
    if scope == ExportScope.SELF:
        requester = _as_uuid(filt.get("requester_user_id"))
        stmt = stmt.where(Student.user_id == requester)
    else:
        classroom_id = _as_uuid(filt.get("classroom_id"))
        stmt = stmt.where(Student.classroom_id == classroom_id)
    session_id = _as_uuid(filt.get("session_id"))
    if session_id is not None:
        stmt = stmt.where(Attempt.session_id == session_id)
    exercise_id = _as_uuid(filt.get("exercise_id"))
    if exercise_id is not None:
        stmt = stmt.where(PracticeSession.assignment_id == exercise_id)
    start = _parse_dt(filt.get("from"))
    end = _parse_dt(filt.get("to"))
    if start is not None:
        stmt = stmt.where(col(Attempt.created_at) >= start)
    if end is not None:
        stmt = stmt.where(col(Attempt.created_at) <= end)
    stmt = stmt.order_by(col(Attempt.created_at), col(Attempt.id))
    # 行数护栏：LIMIT 上限+1 探测，超限即拒，不再全量载入（含音频已清理的历史行）
    stmt = stmt.limit(settings.EXPORT_MAX_ROWS + 1)
    rows = session.exec(stmt).all()
    if len(rows) > settings.EXPORT_MAX_ROWS:
        raise ValueError("export_too_many_attempts")
    candidates: list[ExportCandidate] = []
    for attempt, student, user, classroom, practice, exercise in rows:
        snapshot = attempt.item_snapshot or {}
        title = ""
        if isinstance(snapshot, dict):
            raw = snapshot.get("title") or snapshot.get("text") or ""
            title = str(raw).strip()
        created = attempt.created_at
        candidates.append(
            ExportCandidate(
                attempt_id=attempt.id,
                student_id=student.id,
                student_name=student.display_name,
                student_no=(user.username or "") if user is not None else "",
                classroom_code=classroom.code,
                classroom_name=classroom.name,
                session_id=attempt.session_id,
                exercise_id=practice.assignment_id if practice is not None else None,
                exercise_title=exercise.title if exercise is not None else None,
                item_type=attempt.item_type,
                item_id=attempt.item_id,
                item_title=title,
                created_at=created,
                duration_s=float(attempt.duration_s),
                overall=attempt.overall,
                status=attempt.status,
                audio_mime=attempt.audio_mime,
                audio_path=attempt.audio_path,
                audio_purged_at=attempt.audio_purged_at,
            )
        )
    return candidates


def _item_orders(candidates: list[ExportCandidate]) -> dict[tuple[str, uuid.UUID], int]:
    first: dict[tuple[str, uuid.UUID], datetime] = {}
    for candidate in candidates:
        key = (candidate.item_type, candidate.item_id)
        created = candidate.created_at or datetime.min.replace(tzinfo=UTC)
        if key not in first or created < first[key]:
            first[key] = created
    ordered = sorted(first, key=lambda key: (first[key], str(key[1])))
    return {key: index + 1 for index, key in enumerate(ordered)}


def _extension(candidate: ExportCandidate, source: Path | None) -> str:
    if source is not None and source.suffix:
        return source.suffix.lower()
    suffix = Path(candidate.audio_path).suffix.lower()
    if suffix and not suffix.endswith(".playback.wav"):
        return suffix
    return mime_to_suffix(candidate.audio_mime)


def _stamp(candidate: ExportCandidate) -> str:
    created = candidate.created_at or datetime.now(UTC)
    return to_shanghai(created).strftime("%Y%m%d-%H%M%S")


def _score(candidate: ExportCandidate) -> str:
    return str(candidate.overall) if candidate.overall is not None else "NA"


def _short_title(candidate: ExportCandidate) -> str:
    if not candidate.item_title:
        return ""
    return sanitize_component(candidate.item_title, "", 24)


def _type_label(item_type: str) -> str:
    return ITEM_TYPE_LABEL.get(item_type, sanitize_component(item_type, "题目", 16))


def archive_paths(
    candidates: list[ExportCandidate], *, scope: str, group_by_item: bool
) -> dict[uuid.UUID, str]:
    """每个作答在 ZIP 根目录内的相对路径（缺失的不在其中）。"""
    orders = _item_orders(candidates)
    used: set[str] = set()
    paths: dict[uuid.UUID, str] = {}
    for candidate in candidates:
        source = present_source(candidate)
        if source is None:
            continue
        order = orders[(candidate.item_type, candidate.item_id)]
        label = _type_label(candidate.item_type)
        title = _short_title(candidate)
        title_bit = f"_{title}" if title else ""
        stamp = _stamp(candidate)
        score = _score(candidate)
        ext = _extension(candidate, source)
        if scope == ExportScope.CLASSROOM and group_by_item:
            folder = sanitize_component(f"{label}_{order:02d}{title_bit}", label, 60)
            who = sanitize_component(
                candidate.student_name or candidate.student_no or "学生",
                "学生",
                40,
            )
            relative = f"{folder}/{who}_{stamp}_{score}{ext}"
        else:
            if scope == ExportScope.SELF:
                folder_raw = candidate.exercise_title or _day_folder(candidate)
            else:
                folder_raw = candidate.student_name or candidate.student_no or "学生"
            folder = sanitize_component(folder_raw, "录音", 40)
            relative = f"{folder}/{label}_{order:02d}{title_bit}_{stamp}_{score}{ext}"
        if relative in used:
            stem, suffix = _split_ext(relative)
            relative = f"{stem}_{candidate.attempt_id.hex[:8]}{suffix}"
        used.add(relative)
        paths[candidate.attempt_id] = relative
    return paths


def _day_folder(candidate: ExportCandidate) -> str:
    created = candidate.created_at or datetime.now(UTC)
    return to_shanghai(created).strftime("%Y%m%d")


def _split_ext(relative: str) -> tuple[str, str]:
    slash = relative.rfind("/")
    name = relative[slash + 1 :]
    dot = name.rfind(".")
    if dot <= 0:
        return relative, ""
    return relative[: slash + 1 + dot] if slash >= 0 else name[:dot], name[dot:]


def _manifest_csv(
    candidates: list[ExportCandidate], paths: dict[uuid.UUID, str]
) -> bytes:
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(MANIFEST_COLUMNS)
    for candidate in candidates:
        created = ""
        if candidate.created_at is not None:
            created = to_shanghai(candidate.created_at).strftime("%Y-%m-%d %H:%M:%S")
        missing = 0 if candidate.attempt_id in paths else 1
        writer.writerow(
            [
                str(candidate.attempt_id),
                str(candidate.student_id),
                candidate.student_name,
                candidate.student_no,
                candidate.classroom_code,
                candidate.classroom_name,
                str(candidate.session_id or ""),
                str(candidate.exercise_id or ""),
                candidate.item_type,
                str(candidate.item_id),
                candidate.item_title,
                created,
                f"{candidate.duration_s:.2f}",
                "" if candidate.overall is None else str(candidate.overall),
                candidate.status,
                candidate.audio_mime,
                paths.get(candidate.attempt_id, ""),
                str(missing),
            ]
        )
    return buffer.getvalue().encode("utf-8")


def build_zip(
    candidates: list[ExportCandidate],
    *,
    scope: str,
    group_by_item: bool,
    root_name: str,
    dest: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> BuildResult:
    """写入 ZIP。没有可打包的原始音频时删除半成品并返回错误码，不留空包。"""
    total = len(candidates)
    if on_progress is not None:
        on_progress(0, total)
    if total == 0:
        return BuildResult(
            error="export_empty", included=0, missing=0, byte_size=0, artifact_name=None
        )
    paths = archive_paths(candidates, scope=scope, group_by_item=group_by_item)
    included = len(paths)
    missing = total - included
    if included == 0:
        if on_progress is not None:
            on_progress(total, total)
        return BuildResult(
            error="export_all_missing",
            included=0,
            missing=missing,
            byte_size=0,
            artifact_name=None,
        )
    nbytes = 0
    for candidate in candidates:
        source = present_source(candidate)
        if source is None:
            continue
        try:
            nbytes += source.stat().st_size
        except OSError:
            logger.exception("export could not stat %s", source)
            return BuildResult(
                error="export_failed",
                included=0,
                missing=total,
                byte_size=0,
                artifact_name=None,
            )
    if nbytes > settings.EXPORT_MAX_BYTES:
        return BuildResult(
            error="export_too_large",
            included=0,
            missing=missing,
            byte_size=nbytes,
            artifact_name=None,
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(f".{dest.name}.partial")
    try:
        with zipfile.ZipFile(partial, "w") as archive:
            manifest = zipfile.ZipInfo(f"{root_name}/manifest.csv")
            manifest.compress_type = zipfile.ZIP_STORED
            manifest.flag_bits |= 0x800
            archive.writestr(manifest, _manifest_csv(candidates, paths))
            done = 0
            for candidate in candidates:
                done += 1
                source = present_source(candidate)
                relative = paths.get(candidate.attempt_id)
                if source is not None and relative is not None:
                    info = zipfile.ZipInfo(f"{root_name}/{relative}")
                    info.compress_type = zipfile.ZIP_STORED
                    info.flag_bits |= 0x800
                    with source.open("rb") as handle, archive.open(info, "w") as target:
                        while True:
                            chunk = handle.read(1024 * 1024)
                            if not chunk:
                                break
                            target.write(chunk)
                if on_progress is not None and (done == total or done % 25 == 0):
                    on_progress(done, total)
        partial.replace(dest)
    except Exception:
        partial.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
        raise
    return BuildResult(
        error=None,
        included=included,
        missing=missing,
        byte_size=dest.stat().st_size,
        artifact_name=dest.name,
    )


def root_from_download_name(download_name: str | None) -> str:
    name = download_name or "BELP_export.zip"
    if name.lower().endswith(".zip"):
        name = name[:-4]
    return sanitize_component(name, "BELP_export", 180)


def window_bounds(
    *,
    scope: str,
    start: datetime | None,
    end: datetime | None,
    recent_days: int | None,
) -> tuple[datetime | None, datetime | None]:
    """窗口护栏：课堂默认最近 7 天、学生自助默认最近 90 天，跨度上限一致。

    学生自助 2026-10-29 起与学情 PDF 语义对齐（原「不套窗口」决策废除，
    导出无界防护：query_candidates 不再全量载入历史行）。
    """
    if start is not None and start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    max_days = settings.EXPORT_RECENT_DAYS_MAX
    default_days = (
        settings.EXPORT_RECENT_DAYS_DEFAULT
        if scope == ExportScope.CLASSROOM
        else max_days
    )
    if start is None and end is None:
        days = recent_days if recent_days is not None else default_days
        if days < 1 or days > max_days:
            raise ValueError("export_range_too_wide")
        end_at = datetime.now(UTC)
        return end_at - timedelta(days=days), end_at
    if start is None or end is None:
        raise ValueError("export_range_too_wide")
    # 日期选择器的结束日含当天 23:59:59，比整 N 天多不到一天仍算 N 天。
    if end < start or (end - start) > timedelta(
        days=max_days, hours=23, minutes=59, seconds=59
    ):
        raise ValueError("export_range_too_wide")
    return start, end
