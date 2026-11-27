"""版权/授权台账 + 词库版本历史接口（#517）。

校级（SessionDep，模块闸门挂在装配路由上）：
    GET   /vocabulary/books/{book_id}/license            按词库读取授权
    PATCH /vocabulary/books/{book_id}/license           更新词库授权（仅学校管理员）
    PATCH /vocabulary/words/{word_id}/license           更新词条授权（仅学校管理员）
    GET   /vocabulary/license/alerts                    临期 / 已过期提醒
    GET   /vocabulary/license/audit                    本校授权变更审计
    GET   /vocabulary/license/export.csv                授权清单 CSV（仅学校管理员）
    GET   /vocabulary/books/{book_id}/versions          版本列表
    GET   /vocabulary/books/{book_id}/versions/compare 两版本词条级对比
    POST  /vocabulary/books/{book_id}/versions/{version_no}/rollback  回滚（仅管理员）

平台运营（PlatformSessionDep + PlatformOperatorDep，只读）：
    GET   /admin/vocabulary/license/status              跨校当前授权台账
    GET   /admin/vocabulary/license/audit               跨校授权审计
    GET   /admin/vocabulary/license/export.csv          跨校授权清单 CSV

权限口径：跨校对象按 404 处理不泄露存在性；普通教师不可改授权、不可回滚；
401 只表示登录失效，权限不足一律 403。
"""

import csv
import io
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from sqlmodel import Session, col, select

from app.api.deps import (
    PlatformOperatorDep,
    PlatformSessionDep,
    SchoolAdminDep,
    SessionDep,
    TeacherUserDep,
)
from app.api.routes.vocabulary_shared import _book_visible
from app.models import (
    LICENSE_EXPIRING_DAYS,
    LICENSE_STATUS_ACTIVE,
    LICENSE_STATUS_EXPIRED,
    LICENSE_STATUS_EXPIRING,
    LICENSE_STATUS_MISSING,
    LICENSE_STATUS_NOT_REQUIRED,
    Tenant,
    User,
    VocabularyBook,
    VocabularyBookItem,
    VocabularyBookLicenseDetail,
    VocabularyBookVersion,
    VocabularyBookVersionEntry,
    VocabularyBookVersionList,
    VocabularyLicenseAlertItem,
    VocabularyLicenseAudit,
    VocabularyLicenseAuditItem,
    VocabularyLicenseInfo,
    VocabularyLicenseStatusItem,
    VocabularyLicenseStatusList,
    VocabularyLicenseUpdate,
    VocabularyVersionCompare,
    VocabularyWord,
    VocabularyWordLicenseItem,
)
from app.services import vocab_governance
from app.services.csv_safety import csv_safe

router = APIRouter(tags=["vocabulary"])
admin_router = APIRouter(tags=["admin"])


# ── 内部辅助 ────────────────────────────────────────────────────────


def _get_book_visible(
    session: Session, book_id: uuid.UUID, current_user: User
) -> VocabularyBook:
    book = session.get(VocabularyBook, book_id)
    if book is None or book.tenant_id != current_user.tenant_id:  # type: ignore[union-attr]
        raise HTTPException(status_code=404, detail="词库不存在")
    if not _book_visible(book, current_user):
        raise HTTPException(status_code=403, detail="没有权限查看这个词库")
    return book


def _license_info(
    source_type: str | None,
    owner: str | None,
    ref: str | None,
    expires_at: datetime | None,
    doc_url: str | None,
    note: str | None,
    now: datetime,
) -> VocabularyLicenseInfo:
    return VocabularyLicenseInfo(
        source_type=source_type or "self_built",
        license_owner=owner,
        license_ref=ref,
        license_expires_at=expires_at,
        authorization_doc_url=doc_url,
        license_note=note,
        license_status=vocab_governance.license_status(source_type, expires_at, now),
    )


def _require_school_admin(current_user: User) -> None:
    if current_user.role != "school_admin":
        raise HTTPException(status_code=403, detail="需要学校管理员权限")


def _visible_book_ids(session: Session, user: User) -> set[uuid.UUID]:
    from app.services.vocabulary import visible_book_ids_for

    return visible_book_ids_for(session, user)


def _book_words(session: Session, book_id: uuid.UUID) -> list[VocabularyWord]:
    return list(
        session.exec(
            select(VocabularyWord)
            .join(
                VocabularyBookItem,
                VocabularyBookItem.word_id == VocabularyWord.id,  # ty: ignore[invalid-argument-type]
            )
            .where(VocabularyBookItem.book_id == book_id)  # type: ignore[arg-type]
            .order_by(col(VocabularyBookItem.position))
        ).all()
    )


def _audit_item(
    row: VocabularyLicenseAudit, tenant_map: dict[uuid.UUID, Tenant] | None = None
) -> VocabularyLicenseAuditItem:
    tenant = tenant_map.get(row.tenant_id) if tenant_map else None
    return VocabularyLicenseAuditItem(
        id=row.id,
        target_type=row.target_type,
        book_id=row.book_id,
        word_id=row.word_id,
        actor_id=row.actor_id,
        actor_name=row.actor_name,
        actor_role=row.actor_role,
        changes=row.changes,
        note=row.note,
        created_at=row.created_at,
        tenant_slug=tenant.slug if tenant else None,
        tenant_name=tenant.name_zh if tenant else None,
    )


def _tenant_map(
    session: Session, tenant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Tenant]:
    if not tenant_ids:
        return {}
    return {
        t.id: t
        for t in session.exec(
            select(Tenant).where(col(Tenant.id).in_(tenant_ids))  # type: ignore[operator]
        ).all()
    }


# ── 校级：授权读取 / 更新 ────────────────────────────────────────────


@router.get(
    "/vocabulary/books/{book_id}/license", response_model=VocabularyBookLicenseDetail
)
def read_book_license(
    session: SessionDep, current_user: TeacherUserDep, book_id: uuid.UUID
) -> Any:
    """按词库读取授权：词库级信息 + 词条级授权清单。"""
    book = _get_book_visible(session, book_id, current_user)
    now = vocab_governance.get_datetime_utc()
    words = _book_words(session, book.id)
    word_items = [
        VocabularyWordLicenseItem(
            word_id=w.id,
            headword=w.headword,
            source_type=w.source_type,
            license_owner=w.license_owner,
            license_ref=w.license_ref,
            license_expires_at=w.license_expires_at,
            authorization_doc_url=w.authorization_doc_url,
            license_note=w.license_note,
            license_status=vocab_governance.license_status(
                w.source_type, w.license_expires_at, now
            ),
        )
        for w in words
    ]
    return VocabularyBookLicenseDetail(
        book_id=book.id,
        title=book.title,
        license=_license_info(
            book.source_type,
            book.license_owner,
            book.license_ref,
            book.license_expires_at,
            book.authorization_doc_url,
            book.license_note,
            now,
        ),
        words=word_items,
    )


@router.patch(
    "/vocabulary/books/{book_id}/license", response_model=VocabularyBookLicenseDetail
)
def update_book_license(
    session: SessionDep,
    current_user: TeacherUserDep,
    book_id: uuid.UUID,
    body: VocabularyLicenseUpdate,
) -> Any:
    """更新词库授权（仅学校管理员）；逐字段写前后值审计。

    跨校对象先按 404 处理（不泄露存在性），再判管理员 403。
    """
    book = session.get(VocabularyBook, book_id)
    if book is None or book.tenant_id != current_user.tenant_id:  # type: ignore[union-attr]
        raise HTTPException(status_code=404, detail="词库不存在")
    _require_school_admin(current_user)
    vocab_governance.apply_license_update(
        session,
        target=book,
        target_type="book",
        book_id=book.id,
        word_id=None,
        actor=current_user,
        payload=body.model_dump(exclude_unset=True),
    )
    session.add(book)
    session.commit()
    session.refresh(book)
    now = vocab_governance.get_datetime_utc()
    words = _book_words(session, book.id)
    return VocabularyBookLicenseDetail(
        book_id=book.id,
        title=book.title,
        license=_license_info(
            book.source_type,
            book.license_owner,
            book.license_ref,
            book.license_expires_at,
            book.authorization_doc_url,
            book.license_note,
            now,
        ),
        words=[
            VocabularyWordLicenseItem(
                word_id=w.id,
                headword=w.headword,
                source_type=w.source_type,
                license_owner=w.license_owner,
                license_ref=w.license_ref,
                license_expires_at=w.license_expires_at,
                authorization_doc_url=w.authorization_doc_url,
                license_note=w.license_note,
                license_status=vocab_governance.license_status(
                    w.source_type, w.license_expires_at, now
                ),
            )
            for w in words
        ],
    )


@router.patch("/vocabulary/words/{word_id}/license")
def update_word_license(
    session: SessionDep,
    current_user: TeacherUserDep,
    word_id: uuid.UUID,
    body: VocabularyLicenseUpdate,
) -> Any:
    """更新词条授权（仅学校管理员）；跨校词条按 404 处理。"""
    word = session.get(VocabularyWord, word_id)
    if word is None or word.tenant_id != current_user.tenant_id:  # type: ignore[union-attr]
        raise HTTPException(status_code=404, detail="词条不存在")
    _require_school_admin(current_user)
    vocab_governance.apply_license_update(
        session,
        target=word,
        target_type="word",
        book_id=None,
        word_id=word.id,
        actor=current_user,
        payload=body.model_dump(exclude_unset=True),
    )
    session.add(word)
    session.commit()
    session.refresh(word)
    now = vocab_governance.get_datetime_utc()
    return _license_info(
        word.source_type,
        word.license_owner,
        word.license_ref,
        word.license_expires_at,
        word.authorization_doc_url,
        word.license_note,
        now,
    )


# ── 校级：到期提醒 / 审计 / CSV ──────────────────────────────────────


@router.get(
    "/vocabulary/license/alerts", response_model=list[VocabularyLicenseAlertItem]
)
def list_license_alerts(
    session: SessionDep,
    current_user: TeacherUserDep,
    days: int = Query(default=LICENSE_EXPIRING_DAYS, ge=1, le=365),
) -> Any:
    """临期（窗口内）/ 已过期的词库与词条；教师只见本人可见词库，管理员见全校。"""
    now = vocab_governance.get_datetime_utc()
    if current_user.role == "school_admin":
        books = list(
            session.exec(
                select(VocabularyBook).where(
                    VocabularyBook.tenant_id == current_user.tenant_id  # type: ignore[union-attr]
                )
            ).all()
        )
    else:
        book_ids = _visible_book_ids(session, current_user)
        books = list(
            session.exec(
                select(VocabularyBook).where(col(VocabularyBook.id).in_(book_ids))  # type: ignore[operator]
            ).all()
        )

    alerts: list[VocabularyLicenseAlertItem] = []
    for book in books:
        book_status = vocab_governance.license_status(
            book.source_type, book.license_expires_at, now, expiring_days=days
        )
        if book_status in (LICENSE_STATUS_EXPIRING, LICENSE_STATUS_EXPIRED):
            alerts.append(
                VocabularyLicenseAlertItem(
                    target_type="book",
                    book_id=book.id,
                    book_title=book.title,
                    source_type=book.source_type,
                    license_owner=book.license_owner,
                    license_ref=book.license_ref,
                    license_expires_at=book.license_expires_at,
                    authorization_doc_url=book.authorization_doc_url,
                    license_status=book_status,
                )
            )
        for word in _book_words(session, book.id):
            word_status = vocab_governance.license_status(
                word.source_type, word.license_expires_at, now, expiring_days=days
            )
            if word_status in (LICENSE_STATUS_EXPIRING, LICENSE_STATUS_EXPIRED):
                alerts.append(
                    VocabularyLicenseAlertItem(
                        target_type="word",
                        book_id=book.id,
                        book_title=book.title,
                        word_id=word.id,
                        headword=word.headword,
                        source_type=word.source_type,
                        license_owner=word.license_owner,
                        license_ref=word.license_ref,
                        license_expires_at=word.license_expires_at,
                        authorization_doc_url=word.authorization_doc_url,
                        license_status=word_status,
                    )
                )
    return alerts


@router.get(
    "/vocabulary/license/audit", response_model=list[VocabularyLicenseAuditItem]
)
def list_license_audit(
    session: SessionDep,
    current_user: TeacherUserDep,
    book_id: uuid.UUID | None = Query(default=None),
    word_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    """本校授权变更审计，按时间倒序。"""
    stmt = select(VocabularyLicenseAudit).where(
        VocabularyLicenseAudit.tenant_id == current_user.tenant_id  # type: ignore[union-attr]
    )
    if book_id is not None:
        stmt = stmt.where(VocabularyLicenseAudit.book_id == book_id)  # type: ignore[arg-type]
    if word_id is not None:
        stmt = stmt.where(VocabularyLicenseAudit.word_id == word_id)  # type: ignore[arg-type]
    rows = list(
        session.exec(
            stmt.order_by(col(VocabularyLicenseAudit.created_at).desc()).limit(limit)
        ).all()
    )
    return [_audit_item(row) for row in rows]


def _license_csv_rows(
    session: Session,
    books: list[VocabularyBook],
    now: datetime,
    tenant_labels: dict[uuid.UUID, str] | None = None,
) -> list[list[object]]:
    rows: list[list[object]] = []
    for book in books:
        tenant_label = tenant_labels.get(book.tenant_id) if tenant_labels else None
        words = _book_words(session, book.id)
        targets: list[
            tuple[str, str | None, str | None, str | None, datetime | None, str | None]
        ] = [
            (
                book.title,
                book.source_type,
                book.license_owner,
                book.license_ref or book.authorization_doc_url,
                book.license_expires_at,
                book.source_type,
            )
        ]
        for word in words:
            targets.append(
                (
                    f"{book.title} · {word.headword}",
                    word.source_type,
                    word.license_owner,
                    word.license_ref or word.authorization_doc_url,
                    word.license_expires_at,
                    word.source_type,
                )
            )
        for label, source_type, owner, ref, expires_at, _ in targets:
            status = vocab_governance.license_status(source_type, expires_at, now)
            row: list[object] = [
                csv_safe(label),
                csv_safe(source_type),
                csv_safe(owner or ""),
                csv_safe(ref or ""),
                expires_at.isoformat() if expires_at else "",
                csv_safe(status),
            ]
            if tenant_labels is not None:
                row.insert(0, csv_safe(tenant_label or ""))
            rows.append(row)
    return rows


def _license_csv_response(
    rows: list[list[object]], filename: str, include_tenant: bool = False
) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    header = (
        ["学校", "词库/词条", "source_type", "授权方", "凭证", "到期日", "状态"]
        if include_tenant
        else ["词库/词条", "source_type", "授权方", "凭证", "到期日", "状态"]
    )
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        content=("\ufeff" + buffer.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/vocabulary/license/export.csv")
def export_license_csv(session: SessionDep, current_user: SchoolAdminDep) -> Response:
    """授权清单 CSV（学校管理员）：词库/词条、来源类型、授权方、凭证、到期日、状态。"""
    now = vocab_governance.get_datetime_utc()
    books = list(
        session.exec(
            select(VocabularyBook).where(
                VocabularyBook.tenant_id == current_user.tenant_id  # type: ignore[union-attr]
            )
        ).all()
    )
    rows = _license_csv_rows(session, books, now)
    return _license_csv_response(rows, "vocabulary-license.csv")


# ── 校级：版本历史 / 对比 / 回滚 ─────────────────────────────────────


def _version_entry(row: VocabularyBookVersion) -> VocabularyBookVersionEntry:
    return VocabularyBookVersionEntry(
        version_no=row.version_no,
        action=row.action,
        summary=row.summary,
        content_hash=row.content_hash,
        actor_id=row.actor_id,
        actor_name=row.actor_name,
        actor_role=row.actor_role,
        word_count=len(row.snapshot or []),
        created_at=row.created_at,
    )


@router.get(
    "/vocabulary/books/{book_id}/versions", response_model=VocabularyBookVersionList
)
def list_book_versions(
    session: SessionDep, current_user: TeacherUserDep, book_id: uuid.UUID
) -> Any:
    """词库版本列表（版本号倒序）；跨校不可见。"""
    book = _get_book_visible(session, book_id, current_user)
    rows = vocab_governance.list_versions(session, book)
    return VocabularyBookVersionList(
        items=[_version_entry(row) for row in rows], total=len(rows)
    )


@router.get(
    "/vocabulary/books/{book_id}/versions/compare",
    response_model=VocabularyVersionCompare,
)
def compare_book_versions(
    session: SessionDep,
    current_user: TeacherUserDep,
    book_id: uuid.UUID,
    from_version: int = Query(..., ge=1),
    to_version: int = Query(..., ge=1),
) -> Any:
    """两版本词条级对比：新增 / 删除 / 变更（释义 / 例句 / 词法 / 词形）。"""
    book = _get_book_visible(session, book_id, current_user)
    from_row = vocab_governance.get_version_or_404(session, book, from_version)
    to_row = vocab_governance.get_version_or_404(session, book, to_version)
    diff = vocab_governance.compare_versions(from_row, to_row)
    return VocabularyVersionCompare(
        book_id=book.id,
        from_version_no=from_version,
        to_version_no=to_version,
        added=diff["added"],
        removed=diff["removed"],
        changed=diff["changed"],
        total_changed=len(diff["changed"]),
    )


@router.post(
    "/vocabulary/books/{book_id}/versions/{version_no}/rollback",
    response_model=VocabularyBookVersionEntry,
)
def rollback_book_version(
    session: SessionDep,
    current_user: TeacherUserDep,
    book_id: uuid.UUID,
    version_no: int,
) -> Any:
    """回滚到指定版本：词库内容还原为目标快照，并生成一条新的 rollback 版本。

    仅学校管理员可执行；跨校词库先 404。已有发布任务快照
    （assignment.snapshot_items）不受影响。
    """
    book = session.get(VocabularyBook, book_id)
    if book is None or book.tenant_id != current_user.tenant_id:  # type: ignore[union-attr]
        raise HTTPException(status_code=404, detail="词库不存在")
    _require_school_admin(current_user)
    target = vocab_governance.get_version_or_404(session, book, version_no)
    new_row = vocab_governance.rollback_to_version(session, book, target, current_user)
    session.commit()
    session.refresh(book)
    return _version_entry(new_row)


# ── 平台运营：跨校只读 ───────────────────────────────────────────────


@admin_router.get(
    "/admin/vocabulary/license/audit", response_model=list[VocabularyLicenseAuditItem]
)
def admin_list_license_audit(
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
    book_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    """平台跨校授权审计（只读）；附学校码与校名。"""
    stmt = select(VocabularyLicenseAudit)
    if book_id is not None:
        stmt = stmt.where(VocabularyLicenseAudit.book_id == book_id)  # type: ignore[arg-type]
    rows = list(
        session.exec(
            stmt.order_by(col(VocabularyLicenseAudit.created_at).desc()).limit(limit)
        ).all()
    )
    tenant_map = _tenant_map(session, [r.tenant_id for r in rows])
    return [_audit_item(row, tenant_map) for row in rows]


@admin_router.get(
    "/admin/vocabulary/license/status",
    response_model=VocabularyLicenseStatusList,
)
def admin_list_license_status(
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
    tenant: str | None = Query(default=None),
    book: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=1000),
) -> Any:
    """平台跨校授权台账（只读当前状态）：按学校 / 词库 / 状态筛选。

    只读：不写授权、不复用学校 token；状态口径见
    :func:`vocab_governance.license_gap_status`。``active`` 筛选同时纳入
    ``not_required``（免授权来源）。
    """
    allowed_statuses = {
        LICENSE_STATUS_ACTIVE,
        LICENSE_STATUS_EXPIRING,
        LICENSE_STATUS_EXPIRED,
        LICENSE_STATUS_MISSING,
    }
    if status is not None and status not in allowed_statuses:
        raise HTTPException(status_code=422, detail="vocabulary_license_status_invalid")

    now = vocab_governance.get_datetime_utc()
    stmt = select(VocabularyBook)
    if book:
        stmt = stmt.where(col(VocabularyBook.title).ilike(f"%{book.strip()}%"))
    books = list(session.exec(stmt).all())

    tenant_map = _tenant_map(session, [b.tenant_id for b in books])
    tenant_query = tenant.strip().lower() if tenant and tenant.strip() else None

    def _tenant_matches(t: Tenant | None) -> bool:
        if tenant_query is None or t is None:
            return tenant_query is None
        haystack = f"{t.slug} {t.name_zh} {t.name_en or ''}".lower()
        return tenant_query in haystack

    def _status_matches(item_status: str) -> bool:
        if status is None:
            return True
        if status == LICENSE_STATUS_ACTIVE:
            return item_status in (LICENSE_STATUS_ACTIVE, LICENSE_STATUS_NOT_REQUIRED)
        return item_status == status

    items: list[VocabularyLicenseStatusItem] = []
    for book_row in books:
        tenant_row = tenant_map.get(book_row.tenant_id)
        if not _tenant_matches(tenant_row):
            continue
        item_status = vocab_governance.license_gap_status(
            book_row.source_type,
            book_row.license_owner,
            book_row.license_ref,
            book_row.authorization_doc_url,
            book_row.license_expires_at,
            now,
        )
        if not _status_matches(item_status):
            continue
        items.append(
            VocabularyLicenseStatusItem(
                book_id=book_row.id,
                title=book_row.title,
                tenant_slug=tenant_row.slug if tenant_row else None,
                tenant_name=tenant_row.name_zh if tenant_row else None,
                source_type=book_row.source_type,
                license_status=item_status,
                license_owner=book_row.license_owner,
                license_ref=book_row.license_ref,
                authorization_doc_url=book_row.authorization_doc_url,
                license_expires_at=book_row.license_expires_at,
                license_note=book_row.license_note,
                created_at=book_row.created_at,
            )
        )

    items.sort(
        key=lambda item: (
            (item.tenant_name or item.tenant_slug or "").lower(),
            item.title.lower(),
        )
    )
    total = len(items)
    return VocabularyLicenseStatusList(items=items[:limit], total=total)


@admin_router.get("/admin/vocabulary/license/export.csv")
def admin_export_license_csv(
    session: PlatformSessionDep, _operator: PlatformOperatorDep
) -> Response:
    """平台跨校授权清单 CSV（只读）：首列为学校，口径与台账页一致。"""
    now = vocab_governance.get_datetime_utc()
    books = list(session.exec(select(VocabularyBook)).all())
    tenant_map = _tenant_map(session, [b.tenant_id for b in books])
    tenant_labels = {
        tenant_id: (tenant.name_zh or tenant.slug)
        for tenant_id, tenant in tenant_map.items()
    }
    rows = _license_csv_rows(session, books, now, tenant_labels)
    return _license_csv_response(
        rows, "vocabulary-license-all.csv", include_tenant=True
    )
