"""词汇词条内容治理审核接口（AC4）。

校级（教师 / 学校管理员，SessionDep）：
    GET  /vocabulary/reviews              审核队列（状态/来源/词库/课堂/关键词过滤）
    POST /vocabulary/reviews              批量通过 / 拒绝（全有或全无，逐词审计）
    GET  /vocabulary/reviews/audit        本校审核留痕

平台运营（PlatformSessionDep + PlatformOperatorDep，只读）：
    GET  /admin/vocabulary/reviews        跨校队列（附学校码/校名）
    GET  /admin/vocabulary/reviews/audit  跨校审核留痕

权限口径：教师只能审自己拥有的班级词库词条；school_admin 审全校；
平台只读不可改。401 只表示登录失效；权限不足一律 403；跨校/不存在按 404。
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import col, select

from app.api.deps import (
    PlatformOperatorDep,
    PlatformSessionDep,
    SessionDep,
    TeacherUserDep,
    require_module,
)
from app.models import (
    Tenant,
    VocabularyContentReviewAudit,
    VocabularyContentReviewList,
    VocabularyReviewActionRequest,
    VocabularyReviewActionResult,
    VocabularyReviewAuditItem,
    VocabularyReviewItem,
    VocabularyWord,
)
from app.services.vocabulary import (
    _first_book_of_words,
    list_review_audit,
    list_review_queue,
    review_words,
)

router = APIRouter(tags=["vocabulary"])
admin_router = APIRouter(tags=["admin"])


def _tenant_map(
    session: SessionDep, tenant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Tenant]:
    if not tenant_ids:
        return {}
    return {
        t.id: t
        for t in session.exec(
            select(Tenant).where(col(Tenant.id).in_(tenant_ids))  # type: ignore[operator]
        ).all()
    }


def _review_item(
    word: VocabularyWord,
    *,
    book_map: dict[uuid.UUID, tuple[uuid.UUID, str]],
    tenant_map: dict[uuid.UUID, Tenant] | None = None,
) -> VocabularyReviewItem:
    book_id, book_title = book_map.get(word.id, (None, None))
    tenant = tenant_map.get(word.tenant_id) if tenant_map else None
    return VocabularyReviewItem(
        word_id=word.id,
        headword=word.headword,
        part_of_speech=word.part_of_speech,
        meaning_zh=word.meaning_zh,
        source=word.source,
        review_status=word.review_status,
        review_note=word.review_note,
        version=word.version,
        book_id=book_id,
        book_title=book_title,
        reviewer_id=word.reviewer_id,
        reviewed_at=word.reviewed_at,
        tenant_slug=tenant.slug if tenant else None,
        tenant_name=tenant.name_zh if tenant else None,
    )


def _audit_item(
    row: VocabularyContentReviewAudit,
    *,
    tenant_map: dict[uuid.UUID, Tenant] | None = None,
) -> VocabularyReviewAuditItem:
    tenant = tenant_map.get(row.tenant_id) if tenant_map else None
    return VocabularyReviewAuditItem(
        id=row.id,
        word_id=row.word_id,
        headword=row.headword,
        actor_id=row.actor_id,
        actor_name=row.actor_name,
        actor_role=row.actor_role,
        action=row.action,
        from_status=row.from_status,
        to_status=row.to_status,
        note=row.note,
        created_at=row.created_at,
        tenant_slug=tenant.slug if tenant else None,
        tenant_name=tenant.name_zh if tenant else None,
    )


# ── 校级：教师 / 学校管理员 ────────────────────────────────────────


@router.get(
    "/vocabulary/reviews",
    response_model=VocabularyContentReviewList,
    dependencies=[Depends(require_module("vocabulary"))],
)
def list_vocabulary_reviews(
    session: SessionDep,
    current_user: TeacherUserDep,
    status: str | None = Query(default="pending"),
    source: str | None = Query(default=None),
    book_id: uuid.UUID | None = Query(default=None),
    classroom_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """审核队列：教师只见本人班级库；school_admin 见全校。"""
    words, counts, total = list_review_queue(
        session,
        viewer=current_user,
        status=status,
        source=source,
        book_id=book_id,
        classroom_id=classroom_id,
        q=q,
        offset=offset,
        limit=limit,
    )
    book_map = _first_book_of_words(session, [w.id for w in words])
    items = [_review_item(word, book_map=book_map) for word in words]
    return VocabularyContentReviewList(
        items=items,
        total=total,
        pending_count=counts["pending"],
        rejected_count=counts["rejected"],
        approved_count=counts["approved"],
    )


@router.post(
    "/vocabulary/reviews",
    response_model=VocabularyReviewActionResult,
    dependencies=[Depends(require_module("vocabulary"))],
)
def review_vocabulary_words(
    session: SessionDep,
    current_user: TeacherUserDep,
    body: VocabularyReviewActionRequest,
) -> Any:
    """批量审核：非 pending 冲突 409；拒绝必须填意见；整批全有或全无，逐词审计。"""
    updated, target = review_words(
        session,
        viewer=current_user,
        word_ids=body.word_ids,
        action=body.action,
        note=body.note,
    )
    return VocabularyReviewActionResult(updated=updated, status=target)


@router.get(
    "/vocabulary/reviews/audit",
    response_model=list[VocabularyReviewAuditItem],
    dependencies=[Depends(require_module("vocabulary"))],
)
def vocabulary_review_audit(
    session: SessionDep,
    current_user: TeacherUserDep,
    word_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    """本校审核留痕（通过 / 拒绝 / 审核后编辑回退），按时间倒序。"""
    rows = list_review_audit(session, viewer=current_user, word_id=word_id, limit=limit)
    return [_audit_item(row) for row in rows]


# ── 平台运营：跨校只读 ─────────────────────────────────────────────


@admin_router.get(
    "/admin/vocabulary/reviews", response_model=VocabularyContentReviewList
)
def admin_list_vocabulary_reviews(
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
    status: str | None = Query(default="pending"),
    source: str | None = Query(default=None),
    book_id: uuid.UUID | None = Query(default=None),
    classroom_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """平台跨校审核队列（只读）；附学校码与校名。"""
    words, counts, total = list_review_queue(
        session,
        viewer=None,
        platform=True,
        status=status,
        source=source,
        book_id=book_id,
        classroom_id=classroom_id,
        q=q,
        offset=offset,
        limit=limit,
    )
    book_map = _first_book_of_words(session, [w.id for w in words])
    tenant_map = _tenant_map(session, [w.tenant_id for w in words])
    items = [
        _review_item(word, book_map=book_map, tenant_map=tenant_map) for word in words
    ]
    return VocabularyContentReviewList(
        items=items,
        total=total,
        pending_count=counts["pending"],
        rejected_count=counts["rejected"],
        approved_count=counts["approved"],
    )


@admin_router.get(
    "/admin/vocabulary/reviews/audit",
    response_model=list[VocabularyReviewAuditItem],
)
def admin_vocabulary_review_audit(
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
    word_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    """平台跨校审核留痕（只读）；附学校码与校名。"""
    rows = list_review_audit(
        session, viewer=None, word_id=word_id, limit=limit, platform=True
    )
    tenant_map = _tenant_map(session, [r.tenant_id for r in rows])
    return [_audit_item(row, tenant_map=tenant_map) for row in rows]
