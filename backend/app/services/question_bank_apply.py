"""题库导入落库：单事务确认导入（咨询锁 + 指纹对账 + 整体回滚）。"""

import uuid

from fastapi import (
    HTTPException,
)
from sqlalchemy import (
    text,
)
from sqlalchemy.exc import (
    IntegrityError,
)
from sqlmodel import (
    Session,
)

from app import (
    crud,
)
from app.models import (
    Instruction,
    Passage,
    QuestionBankCreatedItem,
    QuestionBankImportResult,
    QuestionBankImportTypeResult,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    User,
)
from app.services import (
    content_access,
)
from app.services.question_bank_parse import (
    ParsedFile,
)
from app.services.question_bank_plan import (
    QuestionBankPlan,
    _excerpt,
    plan_fingerprint,
    plan_import,
)
from app.services.question_bank_ref import (
    _load_reference,
)
from app.services.question_bank_spec import (
    IMPORT_ADVISORY_LOCK_KEY,
    MAX_ISSUES,
    QUESTION_BANK_TYPE_ORDER,
    TYPE_INSTRUCTION,
    TYPE_PASSAGE,
    TYPE_QUESTION,
    TYPE_REPEAT,
    _generate_slug,
    _norm_text,
)


def _commit(session: Session) -> None:
    """提交封装：测试可注入失败验证整体回滚（vocab_levels 同款）。"""
    session.commit()


def apply_import(
    session: Session,
    parsed: ParsedFile,
    include_lines: set[tuple[str, int]] | None = None,
    expected_fingerprint: str | None = None,
    owner: User | None = None,
) -> QuestionBankImportResult:
    """确认导入：单事务落库；任何 DB 异常整体回滚。

    owner 为导入人：新建题目与主题记为其创建；挂靠他人篇目的复述句在规划时
    已记为错误行（跳过，不影响其余行）。

    并发防重：事务级咨询锁（pg_advisory_xact_lock）串行化所有导入确认——
    适合 PostgreSQL 多进程部署（进程内锁无效）。文件解析在锁外完成；
    拿到锁后**重新**查重规划（READ COMMITTED 下能看到刚提交的他批导入），
    两位老师同时导入相同内容时，后拿锁的一批会全部判重跳过。锁随事务
    提交/回滚自动释放。
    """
    decisions = include_lines or set()
    try:
        # Connection.execute：事务内取咨询锁（SQLModel Session.exec 不收原生 SQL 参数）
        session.connection().execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": IMPORT_ADVISORY_LOCK_KEY},
        )
        # 指纹对账（锁内、与最新库状态比对）：老师确认的是预览时的内容与
        # 候选快照——文件被改、候选题被改、重复格局变化都会失配，要求重新
        # 预览。咨询锁只防同时写入，不能证明「确认过的是当前内容」。
        # 比对用**无决策基线**：new_topics/批内格局受勾选影响（勾了疑似行
        # 其新主题才注册），带着决策算指纹会让正常导入永远 422（评审 P2）。
        # 基线（无决策）对账：指纹比对 + 勾选 token 核验都用它——勾选会让
        # 部分疑似行进入待创建列表、使后续同批同款行在决策计划里变成完全
        # 重复，那是勾选的预期结果（按 exact 正常跳过），不是「预览过期」
        # （评审 P2）；对完全重复行提交勾选仍是过期（基线里它不是疑似）
        # 共享一份题库引用快照：baseline 与决策规划只差勾选，_load_reference
        # 的多趟全表流式扫描（NFKC 归一查重）在本锁内只跑一次
        shared_ref = _load_reference(session, parsed)
        baseline = plan_import(session, parsed, editor=owner, ref=shared_ref)
        if expected_fingerprint and plan_fingerprint(baseline) != expected_fingerprint:
            session.rollback()
            raise HTTPException(
                status_code=422,
                detail="预览结果已变化（文件或题库内容有更新），请重新预览后再确认导入",
            )
        baseline_keys = {(item.type, item.line) for item in baseline.suspected_rows}
        stale = decisions - baseline_keys
        if stale:
            sample = "、".join(f"{t}:{ln}" for t, ln in sorted(stale)[:3])
            session.rollback()
            raise HTTPException(
                status_code=422,
                detail=(
                    f"预览结果已变化（{sample} 不再是疑似重复行），"
                    "请重新预览后再确认导入"
                ),
            )
        plan = plan_import(session, parsed, include_lines, editor=owner, ref=shared_ref)
        owner_id = content_access.owner_for(owner) if owner is not None else None
        created_scenarios = _create_scenarios(session, plan, owner_id)
        created_passages, created_items = _create_passages(session, plan, owner_id)
        created_items.extend(
            _create_repeat_sentences(session, plan, owner_id, created_passages)
        )
        created_items.extend(
            _create_questions(session, plan, owner_id, created_scenarios)
        )
        created_items.extend(_create_instructions(session, plan, owner_id))
        _commit(session)
    except HTTPException:
        session.rollback()
        raise
    except IntegrityError as exc:
        # 咨询锁 + 锁内重查下不应发生（外键等极端竞态兜底）：明确 409
        # 而不是 500，老师重新预览即可对账
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="导入内容与其他操作冲突（可能刚被他人导入），请重新预览",
        ) from exc
    except Exception as exc:
        session.rollback()
        raise HTTPException(
            status_code=500, detail="导入失败，已整体回滚，请重试"
        ) from exc

    return _build_import_result(plan, decisions, created_items)


def _create_scenarios(
    session: Session, plan: QuestionBankPlan, owner_id: uuid.UUID | None
) -> dict[str, Scenario]:
    """新建主题（归一键 → 对象），供问答题挂靠。"""
    created_scenarios: dict[str, Scenario] = {}
    for topic in plan.new_topics:
        scenario = Scenario(topic=topic, is_active=True, owner_id=owner_id)
        session.add(scenario)
        created_scenarios[_norm_text(topic)] = scenario
    session.flush()  # 分配 scenario.id
    return created_scenarios


def _create_passages(
    session: Session, plan: QuestionBankPlan, owner_id: uuid.UUID | None
) -> tuple[dict[str, Passage], list[QuestionBankCreatedItem]]:
    """新建篇目（含 slug 去重与单元推导），flush 出 id 供复述句挂靠。"""
    created_items: list[QuestionBankCreatedItem] = []
    used_slugs = set(plan.existing_slugs)
    used_slugs = set(plan.existing_slugs)
    created_passages: dict[str, Passage] = {}
    for item in plan.creates[TYPE_PASSAGE]:
        payload = item.payload
        passage = Passage(
            title=payload["title"],
            topic=crud.derive_passage_topic(
                session, payload.get("unit_id"), payload["topic"]
            ),
            cefr_band=payload["cefr_band"],
            text=payload["text"],
            translation=payload["translation"],
            audio_url=payload["audio_url"],
            suggested_seconds=payload["suggested_seconds"],
            is_active=payload["is_active"],
            slug=_generate_slug(payload["title"], used_slugs),
            unit_id=payload.get("unit_id"),
            owner_id=owner_id,
        )
        session.add(passage)
        created_passages[_norm_text(passage.title)] = passage
        created_items.append(
            QuestionBankCreatedItem(
                type=TYPE_PASSAGE,
                id=str(passage.id),
                label=payload["title"],
                needs_audio=False,
                audio_missing=not payload["audio_url"],
            )
        )
    session.flush()  # 分配 passage.id，供复述句挂靠
    return created_passages, created_items


def _create_repeat_sentences(
    session: Session,
    plan: QuestionBankPlan,
    owner_id: uuid.UUID | None,
    created_passages: dict[str, Passage],
) -> list[QuestionBankCreatedItem]:
    """新建复述句（按篇目/全局分别续序号，挂靠他人篇目继承其归属）。"""
    created_items: list[QuestionBankCreatedItem] = []
    per_passage_order = dict(plan.max_sentence_order_by_passage)
    global_order = plan.max_sentence_order_global
    for item in plan.creates[TYPE_REPEAT]:
        payload = item.payload
        passage_id = item.passage_id
        if passage_id is None and item.planned_passage_title is not None:
            planned = created_passages.get(item.planned_passage_title)
            passage_id = planned.id if planned is not None else None
        sentence_owner_id = owner_id
        if passage_id is not None:
            order = per_passage_order.get(passage_id, 0) + 1
            per_passage_order[passage_id] = order
            if item.passage_id is not None:
                existing = session.get(Passage, item.passage_id)
                if existing is not None:
                    sentence_owner_id = content_access.passage_owner(session, existing)
        else:
            global_order += 1
            order = global_order
        sentence = RepeatSentence(
            passage_id=passage_id,
            order_index=order,
            text=payload["text"],
            translation=payload["translation"],
            audio_url=payload["audio_url"],
            suggested_seconds=payload["suggested_seconds"],
            replay_limit=payload["replay_limit"],
            exam_kind=payload["exam_kind"],
            exam_level=payload["exam_level"],
            owner_id=sentence_owner_id,
        )
        session.add(sentence)
        created_items.append(
            QuestionBankCreatedItem(
                type=TYPE_REPEAT,
                id=str(sentence.id),
                label=_excerpt(payload["text"]),
                needs_audio=True,  # 题面不显示文字 + 模考开考检查（见 exam-audio-check）
                audio_missing=not payload["audio_url"],
            )
        )
    return created_items


def _create_questions(
    session: Session,
    plan: QuestionBankPlan,
    owner_id: uuid.UUID | None,
    created_scenarios: dict[str, Scenario],
) -> list[QuestionBankCreatedItem]:
    """新建问答题（按主题续 order_index）。"""
    created_items: list[QuestionBankCreatedItem] = []
    question_order = dict(plan.max_question_order)
    for item in plan.creates[TYPE_QUESTION]:
        payload = item.payload
        if item.scenario_id is not None:
            scenario_id = item.scenario_id
        else:
            scenario = created_scenarios[_norm_text(item.new_topic or "")]
            scenario_id = scenario.id
        order = question_order.get(scenario_id, 0) + 1
        question_order[scenario_id] = order
        question = ScenarioQuestion(
            scenario_id=scenario_id,
            band="B1",
            order_index=order,
            text=payload["text"],
            translation=payload["translation"],
            audio_url=payload["audio_url"],
            suggested_seconds=payload["suggested_seconds"],
            exam_kind=payload["exam_kind"],
            exam_level=payload["exam_level"],
            cue_card_bullets=payload["cue_card_bullets"],
            prep_seconds=payload["prep_seconds"],
            owner_id=owner_id,
        )
        session.add(question)
        created_items.append(
            QuestionBankCreatedItem(
                type=TYPE_QUESTION,
                id=str(question.id),
                label=_excerpt(payload["text"]),
                topic=payload["topic"],
                needs_audio=True,  # 自动考试拒收缺音频的非朗读题（exercise.py）
                audio_missing=not payload["audio_url"],
            )
        )
    return created_items


def _create_instructions(
    session: Session, plan: QuestionBankPlan, owner_id: uuid.UUID | None
) -> list[QuestionBankCreatedItem]:
    """新建题目说明（考试音频在 exam_settings 配置，导入恒记缺音频）。"""
    created_items: list[QuestionBankCreatedItem] = []
    for item in plan.creates[TYPE_INSTRUCTION]:
        payload = item.payload
        instruction = Instruction(
            title=payload["title"],
            text=payload["text"],
            suggested_seconds=payload["suggested_seconds"],
            owner_id=owner_id,
        )
        session.add(instruction)
        created_items.append(
            QuestionBankCreatedItem(
                type=TYPE_INSTRUCTION,
                id=str(instruction.id),
                label=payload["title"] or _excerpt(payload["text"]),
                needs_audio=True,  # 自动考试同样要求说明有音频（exam_settings）
                # 说明的考试音频存于 exam_settings.audio_url，导入不写 → 恒缺，
                # 在发布考试的题目设置里配置
                audio_missing=True,
            )
        )
    return created_items


def _build_import_result(
    plan: QuestionBankPlan,
    decisions: set[tuple[str, int]],
    created_items: list[QuestionBankCreatedItem],
) -> QuestionBankImportResult:
    """按类型汇总导入结果（跳过数按勾选回填，缺音频累计）。"""
    sheets = []
    missing_total = 0
    for qtype in QUESTION_BANK_TYPE_ORDER:
        counts = plan.counts[qtype]
        if not any(
            (
                plan.creates[qtype],
                counts.exact_dup,
                counts.suspected,
                counts.invalid,
            )
        ):
            continue
        missing_total += counts.missing_audio
        selected_imported = sum(
            1 for item in plan.creates[qtype] if (qtype, item.line) in decisions
        )
        sheets.append(
            QuestionBankImportTypeResult(
                type=qtype,
                created=len(plan.creates[qtype]),
                skipped_duplicate=counts.exact_dup,
                skipped_suspected=counts.suspected - selected_imported,
                skipped_invalid=counts.invalid,
                missing_audio_count=counts.missing_audio,
            )
        )
    return QuestionBankImportResult(
        sheets=sheets,
        created_topics=plan.new_topics,
        created_items=created_items,
        issues=plan.issues[:MAX_ISSUES],
        missing_audio_total=missing_total,
    )
    return QuestionBankImportResult(
        sheets=sheets,
        created_topics=plan.new_topics,
        created_items=created_items,
        issues=plan.issues[:MAX_ISSUES],
        missing_audio_total=missing_total,
    )
