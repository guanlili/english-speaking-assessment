import uuid
from collections.abc import Callable
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
)

from sqlmodel import (
    Session,
)

from app.models import (
    Instruction,
    Passage,
    QuestionBankImportIssue,
    QuestionBankImportPreview,
    QuestionBankSuspectedItem,
    QuestionBankTypeCount,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    User,
)
from app.services import (
    content_access,
)
from app.services.question_bank_parse import (
    ErrorRow,
    ParsedFile,
    _build_instruction,
    _build_passage,
    _build_question,
    _build_repeat,
    _RawRow,
    _RowError,
)
from app.services.question_bank_ref import (
    _load_reference,
    _Ref,
)
from app.services.question_bank_spec import (
    MAX_ISSUES,
    MAX_SUSPECTED_LISTED,
    QUESTION_BANK_TYPE_ORDER,
    TYPE_INSTRUCTION,
    TYPE_PASSAGE,
    TYPE_QUESTION,
    TYPE_REPEAT,
    _norm_text,
)


@dataclass
class _TypeCounts:
    valid: int = 0
    exact_dup: int = 0
    suspected: int = 0
    invalid: int = 0
    missing_audio: int = 0


@dataclass
class _CreateItem:
    line: int
    payload: dict[str, Any]
    # 听句复述挂靠：命中库内篇目 → passage_id；命中本次导入篇目 → 计划标题；
    # 都没有 → None（独立句）
    passage_id: uuid.UUID | None = None
    planned_passage_title: str | None = None
    # 情景问答主题：命中库内 → scenario_id；否则 new_topic（确认时新建）
    scenario_id: uuid.UUID | None = None
    new_topic: str | None = None


@dataclass
class QuestionBankPlan:
    creates: dict[str, list[_CreateItem]] = field(default_factory=dict)
    counts: dict[str, _TypeCounts] = field(default_factory=dict)
    # 预览指纹原料：每条通过校验的行 (type, line, payload 摘要)——与查重
    # 决策无关（疑似是否勾选导入不影响指纹），预览与确认两侧可比对
    parsed_digests: list[tuple[str, int, str]] = field(default_factory=list)
    # 指纹的疑似候选全量：(type, line, reason, [(id, summary), ...])。
    # 展示层（existing）只取代表一条，指纹必须覆盖全部相关候选——
    # 新增/修改第二条同题候选也要让指纹失配（评审 P2）
    fingerprint_candidates: list[
        tuple[str, int, str, list[tuple[str, dict[str, Any]]]]
    ] = field(default_factory=list)
    issues: list[QuestionBankImportIssue] = field(default_factory=list)
    suspected_rows: list[QuestionBankSuspectedItem] = field(default_factory=list)
    error_rows: list[ErrorRow] = field(default_factory=list)
    new_topics: list[str] = field(default_factory=list)
    unit_fallback_count: int = 0
    standalone_sentence_count: int = 0
    # apply 阶段需要的库内状态（与 plan 同一快照）
    existing_slugs: set[str] = field(default_factory=set)
    max_question_order: dict[uuid.UUID, int] = field(default_factory=dict)
    max_sentence_order_by_passage: dict[uuid.UUID, int] = field(default_factory=dict)
    max_sentence_order_global: int = 0


def _excerpt(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else f"{text[:limit]}…"


def _summarize_payload(qtype: str, payload: dict[str, Any]) -> dict[str, Any]:
    """疑似对照：待导入行 / 同批前序行的关键字段快照（canonical 键）。"""
    if qtype == TYPE_PASSAGE:
        return {
            "title": payload["title"],
            "text": str(payload["text"]),
            "unit": payload.get("unit_title") or "",
            "topic": payload.get("topic") or "",
            "band": payload["cefr_band"],
            "seconds": str(payload["suggested_seconds"]),
            "translation": payload.get("translation") or "",
            "audio": payload.get("audio_url") or "",
            "_active": bool(payload.get("is_active", True)),
        }
    if qtype == TYPE_REPEAT:
        return {
            "text": payload["text"],
            "passage": payload.get("passage_title") or "",
            "seconds": str(payload["suggested_seconds"]),
            "replay": str(payload["replay_limit"]),
            "kind": payload.get("exam_kind") or "",
            "level": payload.get("exam_level") or "",
            "translation": payload.get("translation") or "",
            "audio": payload.get("audio_url") or "",
        }
    if qtype == TYPE_QUESTION:
        return {
            "text": payload["text"],
            "topic": payload["topic"],
            "seconds": str(payload["suggested_seconds"]),
            "kind": payload.get("exam_kind") or "",
            "level": payload.get("exam_level") or "",
            "prep": str(payload.get("prep_seconds") or ""),
            "cue": " / ".join(payload.get("cue_card_bullets") or []),
            "_bullets": list(payload.get("cue_card_bullets") or []),
            "translation": payload.get("translation") or "",
            "audio": payload.get("audio_url") or "",
        }
    return {
        "title": payload.get("title") or "",
        "text": payload["text"],
        "seconds": str(payload["suggested_seconds"]),
    }


def _row_digest(qtype: str, line: int, payload: dict[str, Any]) -> tuple[str, int, str]:
    import hashlib
    import json

    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    # 完整 64 位十六进制摘要：截断摘要对「尾部字符被改」的候选不敏感（评审 P2）
    return (qtype, line, hashlib.sha256(raw.encode("utf-8")).hexdigest())


def plan_fingerprint(plan: QuestionBankPlan) -> str:
    """预览指纹：文件行内容 + 库内查重状态（含疑似两侧快照）的摘要。

    决策无关——老师勾选哪些疑似行不影响指纹；预览与确认各算一次，
    锁内比对，任何一侧内容/候选变化都会失配（评审 P2：只查「还是不是
    疑似」挡不住「候选内容变了」）。
    """
    import hashlib
    import json

    projection = {
        "rows": [list(item) for item in plan.parsed_digests],
        "counts": {
            qtype: [c.exact_dup, c.suspected, c.invalid]
            for qtype, c in plan.counts.items()
        },
        "suspected_candidates": [list(item) for item in plan.fingerprint_candidates],
        "new_topics": plan.new_topics,
    }
    raw = json.dumps(projection, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _suspected(
    plan: QuestionBankPlan,
    qtype: str,
    line: int,
    reason: str,
    incoming: dict[str, str],
    existing: dict[str, str],
    candidates: list[tuple[str, dict[str, Any]]],
) -> QuestionBankSuspectedItem:
    plan.fingerprint_candidates.append(
        (qtype, line, reason, sorted(candidates, key=lambda pair: pair[0]))
    )

    # 展示层只保留可读字段（响应模型 dict[str,str]）；下划线前缀的
    # 指纹专用键（_active/_bullets/_topic_active）只在候选全量里参与比对
    def display(snapshot: dict[str, Any]) -> dict[str, str]:
        return {
            key: value for key, value in snapshot.items() if not key.startswith("_")
        }

    return QuestionBankSuspectedItem(
        type=qtype,
        line=line,
        reason=reason,
        incoming=display(incoming),
        existing=display(existing),
    )


def plan_import(
    session: Session,
    parsed: ParsedFile,
    include_lines: set[tuple[str, int]] | None = None,
    editor: User | None = None,
    ref: _Ref | None = None,
) -> QuestionBankPlan:
    """校验 + 查重 + 兜底解析，产出创建计划（不写库）。

    include_lines：老师逐条勾选「导入」的疑似行 (type, line) 集合。
    空集 = 全部疑似默认跳过。集合中任何 token 未命中**当前**疑似行
    （文件或库状态已变化）→ 422 强制重新预览，绝不沿用旧选择。

    editor：导入人。复述句挂靠到其不可编辑的已有篇目时记为错误行——
    预览、确认、错误文件三处必须传同一个人，口径才一致。

    ref：可传入预取的题库引用快照（只读）。_load_reference 依赖文件
    内容与库状态，与勾选决策无关——确认流程在同一咨询锁内跑
    baseline 与决策两次规划，共享一份 ref 省掉整套全表流式扫描。
    """
    decisions = include_lines or set()
    if ref is None:
        ref = _load_reference(session, parsed)
    plan = QuestionBankPlan(
        existing_slugs=ref.existing_slugs,
        max_question_order=ref.max_question_order,
        max_sentence_order_by_passage=ref.max_sentence_order_by_passage,
        max_sentence_order_global=ref.max_sentence_order_global,
    )
    for qtype in QUESTION_BANK_TYPE_ORDER:
        plan.creates[qtype] = []
        plan.counts[qtype] = _TypeCounts()
    plan.issues.extend(parsed.issues)
    plan.error_rows.extend(parsed.error_rows)

    by_type: dict[str, list[_RawRow]] = {t: [] for t in plan.creates}
    for row in parsed.rows:
        by_type.setdefault(row.qtype, []).append(row)

    _plan_passages(plan, ref, by_type[TYPE_PASSAGE], decisions)
    _plan_repeats(plan, ref, by_type[TYPE_REPEAT], decisions, editor)
    _plan_questions(plan, ref, by_type[TYPE_QUESTION], decisions)
    _plan_instructions(plan, ref, by_type[TYPE_INSTRUCTION], decisions)
    return plan


def _issue(qtype: str, line: int, reason: str) -> QuestionBankImportIssue:
    return QuestionBankImportIssue(type=qtype, line=line, reason=reason)


def _invalid_row(
    plan: QuestionBankPlan, counts: _TypeCounts, qtype: str, row: _RawRow, reason: str
) -> None:
    """记一条解析/身份解析失败的行：计数 + 问题 + 错误行（供前端逐行改）。"""
    counts.invalid += 1
    plan.issues.append(_issue(qtype, row.line, reason))
    plan.error_rows.append(
        ErrorRow(qtype=qtype, line=row.line, reason=reason, cells=row.cells)
    )


def _parse_row(
    plan: QuestionBankPlan,
    counts: _TypeCounts,
    qtype: str,
    row: _RawRow,
    builder: Callable[[dict[str, str]], dict[str, Any]],
) -> dict[str, Any] | None:
    """解析一行：成功则登记解析摘要，失败记错误行并返回 None。"""
    try:
        payload = builder(row.cells)
    except _RowError as exc:
        _invalid_row(plan, counts, qtype, row, exc.reason)
        return None
    plan.parsed_digests.append(_row_digest(qtype, row.line, payload))
    return payload


def _register_suspected(
    plan: QuestionBankPlan,
    counts: _TypeCounts,
    qtype: str,
    row: _RawRow,
    reason: str,
    payload: dict[str, Any],
    existing: dict[str, str],
    candidates: list[tuple[str, dict[str, str]]],
    decisions: set[tuple[str, int]],
) -> bool:
    """登记一条疑似重复；返回本行是否应继续（用户勾选导入才继续）。"""
    counts.suspected += 1
    plan.suspected_rows.append(
        _suspected(
            plan,
            qtype,
            row.line,
            reason,
            _summarize_payload(qtype, payload),
            existing,
            candidates,
        )
    )
    return (qtype, row.line) in decisions


def _count_valid(counts: _TypeCounts, payload: dict[str, Any]) -> None:
    """计入有效行；音频缺失单独计数（不阻断导入，仅前端提示）。"""
    if not payload["audio_url"]:
        counts.missing_audio += 1
    counts.valid += 1


def _plan_passages(
    plan: QuestionBankPlan,
    ref: _Ref,
    rows: list[_RawRow],
    decisions: set[tuple[str, int]],
) -> None:
    counts = plan.counts[TYPE_PASSAGE]
    planned_exact: dict[tuple[str, str], list[tuple[Any, ...]]] = {}
    planned_payloads_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    planned_payloads_by_text: dict[str, dict[str, Any]] = {}
    planned_texts: set[str] = set()

    def _existing_passage_summary(key: tuple[str, str], n_text: str) -> dict[str, str]:
        db_row = ref.passages_by_key.get(key, [None])[0]
        if db_row is None:
            for (_ptitle, p_text), plist in ref.passages_by_key.items():
                if p_text == n_text and plist:
                    db_row = plist[0]
                    break
        if db_row is not None:
            return _summarize_passage_model(db_row, ref)
        payload = planned_payloads_by_key.get(key, [None])[
            0
        ] or planned_payloads_by_text.get(n_text)
        return _summarize_payload(TYPE_PASSAGE, payload) if payload else {}

    for row in rows:
        payload = _parse_row(plan, counts, TYPE_PASSAGE, row, _build_passage)
        if payload is None:
            continue
        n_title, n_text = _norm_text(payload["title"]), _norm_text(payload["text"])
        key = (n_title, n_text)
        # 单元解析必须先于查重：落库时挂单元的篇目 topic 会被派生为单元主题
        # （crud.derive_passage_topic），查重配置若用原始 topic，同一文件重传
        # 会因「落库值≠导入值」被误判疑似重复（评审 P2 实例）
        unit_title_resolved = ""
        topic_resolved = payload["topic"]
        if payload["unit_title"] is not None:
            candidates = ref.units_by_norm.get(_norm_text(payload["unit_title"]), [])
            if len(candidates) > 1:
                _invalid_row(
                    plan,
                    counts,
                    TYPE_PASSAGE,
                    row,
                    "单元匹配到多个同名单元，请改为精确的单元标题",
                )
                continue
            if len(candidates) == 1:
                payload["unit_id"] = candidates[0].id
                unit_title_resolved = candidates[0].title
                topic_resolved = candidates[0].topic
            else:
                plan.unit_fallback_count += 1
        cfg = (
            _norm_text(payload["translation"] or ""),
            payload["cefr_band"],
            payload["suggested_seconds"],
            payload["is_active"],
            _norm_text(unit_title_resolved),
            _norm_text(topic_resolved),
            payload["audio_url"] or "",
        )
        db_cfgs = ref.passage_exact.get(key, [])
        planned_cfgs = planned_exact.get(key, [])
        suspected_reason = None
        if db_cfgs or planned_cfgs:
            if cfg in db_cfgs or cfg in planned_cfgs:
                counts.exact_dup += 1
                continue
            suspected_reason = "疑似重复：同名同正文篇目已存在，但难度/秒数等配置不同"
        elif n_text in ref.passage_texts or n_text in planned_texts:
            # 批内正文集合也要查：同批两篇不同标题、相同正文 → 第二篇疑似
            suspected_reason = "疑似重复：相同正文已存在于其他篇目"
        if suspected_reason is not None:
            passage_candidates = _passage_candidates(ref, key, n_text)
            if not _register_suspected(
                plan,
                counts,
                TYPE_PASSAGE,
                row,
                suspected_reason,
                payload,
                _existing_passage_summary(key, n_text),
                passage_candidates,
                decisions,
            ):
                continue
        _count_valid(counts, payload)
        plan.creates[TYPE_PASSAGE].append(_CreateItem(line=row.line, payload=payload))
        planned_exact.setdefault(key, []).append(cfg)
        planned_payloads_by_key.setdefault(key, []).append(payload)
        planned_payloads_by_text.setdefault(n_text, payload)
        planned_texts.add(n_text)


def _passage_candidates(
    ref: _Ref, key: tuple[str, str], n_text: str
) -> list[tuple[str, dict[str, str]]]:
    """疑似重复时列出库内全部同题候选（按 id 去重并稳定排序）。"""
    db_candidate_rows = [
        *ref.passages_by_key.get(key, []),
        *[
            p
            for (kt, ktext), plist in ref.passages_by_key.items()
            if ktext == n_text
            for p in plist
        ],
    ]
    seen_ids: set[str] = set()
    passage_candidates: list[tuple[str, dict[str, str]]] = []
    for p in sorted(db_candidate_rows, key=lambda item: str(item.id)):
        if str(p.id) in seen_ids:
            continue
        seen_ids.add(str(p.id))
        passage_candidates.append((str(p.id), _summarize_passage_model(p, ref)))
    return passage_candidates


def _pid_key(passage_id: uuid.UUID | None) -> str:
    """挂靠身份键：独立句统一空串（None 与「无挂靠」语义一致）。"""
    return str(passage_id) if passage_id is not None else ""


def _summarize_passage_model(p: Passage, ref: _Ref) -> dict[str, Any]:
    return {
        "title": p.title,
        "text": p.text,
        "unit": ref.unit_titles.get(p.unit_id, "") if p.unit_id else "",
        "topic": p.topic or "",
        "band": p.cefr_band,
        "seconds": str(p.suggested_seconds),
        "translation": p.translation or "",
        "audio": p.audio_url or "",
        "_active": bool(p.is_active),
    }


def _summarize_sentence_model(s: RepeatSentence, ref: _Ref) -> dict[str, Any]:
    return {
        "text": s.text,
        "passage": ref.passage_titles.get(s.passage_id, "") if s.passage_id else "",
        "seconds": str(s.suggested_seconds),
        "replay": str(s.replay_limit),
        "kind": s.exam_kind or "",
        "level": s.exam_level or "",
        "translation": s.translation or "",
        "audio": s.audio_url or "",
    }


def _scenario_active(ref: _Ref, scenario_id: uuid.UUID) -> bool:
    for scenario in ref.scenarios_by_norm.get(
        _norm_text(ref.scenario_topics.get(scenario_id, "")), []
    ):
        if scenario.id == scenario_id:
            return bool(scenario.is_active)
    return True


def _summarize_question_model(q: ScenarioQuestion, ref: _Ref) -> dict[str, Any]:
    return {
        "text": q.text,
        "topic": ref.scenario_topics.get(q.scenario_id, ""),
        "seconds": str(q.suggested_seconds),
        "kind": q.exam_kind or "",
        "level": q.exam_level or "",
        "prep": str(q.prep_seconds or ""),
        "cue": " / ".join(q.cue_card_bullets or []),
        "_bullets": list(q.cue_card_bullets or []),
        "translation": q.translation or "",
        "audio": q.audio_url or "",
        "_topic_active": _scenario_active(ref, q.scenario_id),
    }


def _summarize_instruction_model(i: Instruction) -> dict[str, Any]:
    return {
        "title": i.title or "",
        "text": i.text,
        "seconds": str(i.suggested_seconds),
    }


def _plan_repeats(
    plan: QuestionBankPlan,
    ref: _Ref,
    rows: list[_RawRow],
    decisions: set[tuple[str, int]],
    editor: User | None = None,
) -> None:
    counts = plan.counts[TYPE_REPEAT]
    planned_configs: dict[tuple[str, str], list[tuple[Any, ...]]] = {}
    planned_payloads: dict[tuple[str, str], list[dict[str, Any]]] = {}
    planned_links: dict[str, set[str]] = {}  # n_text → 本批已见的挂靠身份键
    # 本批计划新建的篇目标题（供挂靠；同批多篇同名 → 歧义报错）
    planned_titles: dict[str, int] = {}
    for item in plan.creates[TYPE_PASSAGE]:
        n_title = _norm_text(item.payload["title"])
        planned_titles[n_title] = planned_titles.get(n_title, 0) + 1

    def _existing_sentence_summary(n_text: str, linkage: str) -> dict[str, str]:
        candidates = ref.sentences_by_key.get(n_text, [])
        db_row = next(
            (s for s in candidates if _pid_key(s.passage_id) == linkage),
            None,
        )
        if db_row is None:
            db_row = candidates[0] if candidates else None
        if db_row is not None:
            return _summarize_sentence_model(db_row, ref)
        payload = (planned_payloads.get((linkage, n_text)) or [None])[0]
        if payload is None:
            for (_plink, ptext), plist in planned_payloads.items():
                if ptext == n_text and plist:
                    payload = plist[0]
                    break
        return _summarize_payload(TYPE_REPEAT, payload) if payload else {}

    for row in rows:
        payload = _parse_row(plan, counts, TYPE_REPEAT, row, _build_repeat)
        if payload is None:
            continue
        n_text = _norm_text(payload["text"])
        # 挂靠解析（歧义报错）必须先于查重，且查重按**解析后的对象身份**
        # （passage_id）比较——同名根篇与旧子篇是不同记录，按标题比较会把
        # 挂在不同篇目下的同句误判为完全重复（评审 P2）；降级独立句的身份
        # 键是空串，与库内独立句一致（Ghost 挂靠重传仍判完全重复）
        passage_id, planned_title, linkage, linkage_reason = _resolve_sentence_linkage(
            plan, payload, ref, planned_titles, editor
        )
        if linkage_reason is not None:
            _invalid_row(plan, counts, TYPE_REPEAT, row, linkage_reason)
            continue
        cfg = (
            _norm_text(payload["translation"] or ""),
            payload["suggested_seconds"],
            payload["replay_limit"],
            payload["exam_kind"] or "",
            payload["exam_level"] or "",
            payload["audio_url"] or "",
        )
        db_entries = ref.sentence_configs.get(n_text, [])
        db_cfgs = [c for pid, c in db_entries if _pid_key(pid) == linkage]
        planned_cfgs = planned_configs.get((linkage, n_text), [])
        suspected_reason = None
        if db_cfgs or planned_cfgs:
            if cfg in db_cfgs or cfg in planned_cfgs:
                counts.exact_dup += 1
                continue
            suspected_reason = "疑似重复：相同句子已存在但挂靠或配置不同"
        elif db_entries or n_text in planned_links:
            # 相同句子挂在其他篇目/独立存在：疑似而非完全重复，可勾选导入
            suspected_reason = "疑似重复：相同句子已存在但挂靠或配置不同"
        if suspected_reason is not None:
            sentence_candidates = [
                (str(sentence.id), _summarize_sentence_model(sentence, ref))
                for sentence in sorted(
                    ref.sentences_by_key.get(n_text, []), key=lambda item: str(item.id)
                )
            ]
            if not _register_suspected(
                plan,
                counts,
                TYPE_REPEAT,
                row,
                suspected_reason,
                payload,
                _existing_sentence_summary(n_text, linkage),
                sentence_candidates,
                decisions,
            ):
                continue
        _count_valid(counts, payload)
        plan.creates[TYPE_REPEAT].append(
            _CreateItem(
                line=row.line,
                payload=payload,
                passage_id=passage_id,
                planned_passage_title=planned_title,
            )
        )
        planned_configs.setdefault((linkage, n_text), []).append(cfg)
        planned_payloads.setdefault((linkage, n_text), []).append(payload)
        planned_links.setdefault(n_text, set()).add(linkage)


def _resolve_sentence_linkage(
    plan: QuestionBankPlan,
    payload: dict[str, Any],
    ref: _Ref,
    planned_titles: dict[str, int],
    editor: User | None,
) -> tuple[uuid.UUID | None, str | None, str, str | None]:
    """解析听句复述的挂靠身份。

    返回 (篇目 id, 本批计划篇目标题, 查重身份键, 错误原因)——错误原因非空
    时该行按无效处理。降级独立句的身份键是空串，与库内独立句一致。
    """
    passage_id: uuid.UUID | None = None
    planned_title: str | None = None
    linkage = ""
    if payload["passage_title"] is not None:
        n_title = _norm_text(payload["passage_title"])
        existing_hits = len(ref.root_passages_by_norm.get(n_title, []))
        planned_hits = planned_titles.get(n_title, 0)
        reason = None
        if existing_hits + planned_hits > 1:
            reason = "挂靠篇目匹配到多个同名篇目，请先重命名区分"
        elif (
            existing_hits == 1
            and editor is not None
            and not content_access.can_edit(
                editor, ref.root_passages_by_norm[n_title][0].owner_id
            )
        ):
            reason = (
                "挂靠篇目由其他老师创建，不能往里添加句子；可去掉挂靠篇目作为独立题导入"
            )
        if reason is not None:
            return passage_id, planned_title, linkage, reason
        if existing_hits == 1:
            passage_id = ref.root_passages_by_norm[n_title][0].id
            linkage = _pid_key(passage_id)
        elif planned_hits == 1:
            planned_title = n_title
            linkage = f"new:{n_title}"
        else:
            plan.standalone_sentence_count += 1
    return passage_id, planned_title, linkage, None


def _existing_question_summary(
    ref: _Ref,
    planned_payloads: dict[tuple[str, str], list[dict[str, Any]]],
    scenario: Scenario | None,
    owner: str,
    n_text: str,
) -> dict[str, str]:
    """疑似重复时展示的「已有题目」摘要：先按主题身份查库，退化到全库同文本；
    都没有则从本批已计划的 payload 里找。"""
    db_row = None
    if scenario is not None:
        db_row = (ref.questions_by_key.get((scenario.id, n_text)) or [None])[0]
    if db_row is None:
        for (_sid, ptext), qlist in ref.questions_by_key.items():
            if ptext == n_text and qlist:
                db_row = qlist[0]
                break
    if db_row is not None:
        return _summarize_question_model(db_row, ref)
    payload = (planned_payloads.get((owner, n_text)) or [None])[0]
    if payload is None:
        for (_powner, ptext), plist in planned_payloads.items():
            if ptext == n_text and plist:
                payload = plist[0]
                break
    return _summarize_payload(TYPE_QUESTION, payload) if payload else {}


def _question_cfg(payload: dict[str, Any]) -> tuple[Any, ...]:
    """查重用的配置指纹：配置全同才是完全重复，只同文本算疑似。"""
    return (
        _norm_text(payload["translation"] or ""),
        payload["suggested_seconds"],
        payload["exam_kind"] or "",
        payload["exam_level"] or "",
        tuple(payload["cue_card_bullets"] or ()),
        payload["prep_seconds"] or 0,
        payload["audio_url"] or "",
    )


def _question_dedup_outcome(
    cfg: tuple[Any, ...],
    db_cfgs: list[tuple[Any, ...]],
    planned_cfgs: list[tuple[Any, ...]],
    other_owners: set[uuid.UUID],
    planned_texts: set[str],
    n_text: str,
) -> tuple[bool, str | None]:
    """判定 (是否完全重复, 疑似重复原因)。完全重复直接跳过，疑似交由决策勾选。"""
    if db_cfgs or planned_cfgs:
        if cfg in db_cfgs or cfg in planned_cfgs:
            return True, None
        return False, "疑似重复：该主题下已有相同题目但配置不同"
    if other_owners or n_text in planned_texts:
        return False, "疑似重复：该题目已存在于其他主题"
    return False, None


def _question_suspect_candidates(
    ref: _Ref, n_text: str
) -> list[tuple[str, dict[str, Any]]]:
    """同文本在其他主题下的已有题目，按 id 排序，供疑似重复勾选展示。"""
    rows = [
        q
        for (c_sid, c_text), qlist in ref.questions_by_key.items()
        if c_text == n_text
        for q in qlist
    ]
    return [
        (str(q.id), _summarize_question_model(q, ref))
        for q in sorted(rows, key=lambda item: str(item.id))
    ]


def _plan_questions(
    plan: QuestionBankPlan,
    ref: _Ref,
    rows: list[_RawRow],
    decisions: set[tuple[str, int]],
) -> None:
    counts = plan.counts[TYPE_QUESTION]
    planned_exact: dict[tuple[str, str], list[tuple[Any, ...]]] = {}
    planned_payloads: dict[tuple[str, str], list[dict[str, Any]]] = {}
    planned_texts: set[str] = set()
    new_topic_map: dict[str, str] = {}

    for row in rows:
        payload = _parse_row(plan, counts, TYPE_QUESTION, row, _build_question)
        if payload is None:
            continue
        n_topic, n_text = _norm_text(payload["topic"]), _norm_text(payload["text"])
        # 主题解析（精确优先，歧义报错）必须先于查重：查重按解析后的
        # scenario 身份（scenario_id）比较，不按主题名——travel/Travel 是两个
        # 主题，各自持有同题是疑似重复（可勾选导入）而非完全重复；歧义行
        # 也不能因内容与库内相同而被查重静默跳过、漏掉歧义提示（评审 P2）
        scenario, scenario_reason = _resolve_question_scenario(payload, n_topic, ref)
        if scenario_reason is not None:
            _invalid_row(plan, counts, TYPE_QUESTION, row, scenario_reason)
            continue
        # 身份键：已解析主题用其 id；新主题用规范化主题名作批内伪键
        owner = str(scenario.id) if scenario is not None else f"new:{n_topic}"
        cfg = _question_cfg(payload)
        db_cfgs = (
            ref.question_exact.get((scenario.id, n_text), [])
            if scenario is not None
            else []
        )
        planned_cfgs = planned_exact.get((owner, n_text), [])
        other_owners = ref.question_texts.get(n_text, set())
        is_exact_dup, suspected_reason = _question_dedup_outcome(
            cfg, db_cfgs, planned_cfgs, other_owners, planned_texts, n_text
        )
        if is_exact_dup:
            counts.exact_dup += 1
            continue
        if suspected_reason is not None:
            if not _register_suspected(
                plan,
                counts,
                TYPE_QUESTION,
                row,
                suspected_reason,
                payload,
                _existing_question_summary(
                    ref, planned_payloads, scenario, owner, n_text
                ),
                _question_suspect_candidates(ref, n_text),
                decisions,
            ):
                continue
        if scenario is None and n_topic not in new_topic_map:
            new_topic_map[n_topic] = payload["topic"]
            plan.new_topics.append(payload["topic"])
        _count_valid(counts, payload)
        plan.creates[TYPE_QUESTION].append(
            _CreateItem(
                line=row.line,
                payload=payload,
                scenario_id=scenario.id if scenario is not None else None,
                new_topic=None if scenario is not None else new_topic_map[n_topic],
            )
        )
        planned_exact.setdefault((owner, n_text), []).append(cfg)
        planned_payloads.setdefault((owner, n_text), []).append(payload)
        planned_texts.add(n_text)


def _resolve_question_scenario(
    payload: dict[str, Any], n_topic: str, ref: _Ref
) -> tuple[Scenario | None, str | None]:
    """解析情景问答主题：精确名优先，大小写不同的同名主题歧义报错。"""
    scenario = ref.scenarios_by_exact.get(payload["topic"])
    if scenario is None:
        candidates = ref.scenarios_by_norm.get(n_topic, [])
        if len(candidates) > 1:
            return (
                None,
                "主题匹配到多个大小写不同的同名主题，请使用与题库完全一致的主题名",
            )
        if len(candidates) == 1:
            scenario = candidates[0]
    return scenario, None


def _plan_instructions(
    plan: QuestionBankPlan,
    ref: _Ref,
    rows: list[_RawRow],
    decisions: set[tuple[str, int]],
) -> None:
    counts = plan.counts[TYPE_INSTRUCTION]
    planned_configs: dict[str, list[tuple[Any, ...]]] = {}
    planned_payloads: dict[str, dict[str, Any]] = {}

    def _existing_instruction_summary(n_text: str) -> dict[str, str]:
        db_row = next(
            (i for i in ref.instructions_all if _norm_text(i.text) == n_text), None
        )
        if db_row is not None:
            return _summarize_instruction_model(db_row)
        payload = planned_payloads.get(n_text)
        return _summarize_payload(TYPE_INSTRUCTION, payload) if payload else {}

    for row in rows:
        try:
            payload = _build_instruction(row.cells)
            plan.parsed_digests.append(_row_digest(TYPE_INSTRUCTION, row.line, payload))
        except _RowError as exc:
            counts.invalid += 1
            plan.issues.append(_issue(TYPE_INSTRUCTION, row.line, exc.reason))
            plan.error_rows.append(
                ErrorRow(
                    qtype=TYPE_INSTRUCTION,
                    line=row.line,
                    reason=exc.reason,
                    cells=row.cells,
                )
            )
            continue
        n_text = _norm_text(payload["text"])
        cfg = (_norm_text(payload["title"] or ""), payload["suggested_seconds"])
        db_cfgs = ref.instruction_configs.get(n_text, [])
        planned_cfgs = planned_configs.get(n_text, [])
        if db_cfgs or planned_cfgs:
            if cfg in db_cfgs or cfg in planned_cfgs:
                counts.exact_dup += 1
                continue
            counts.suspected += 1
            instruction_candidates = [
                (str(ins.id), _summarize_instruction_model(ins))
                for ins in ref.instructions_all
                if _norm_text(ins.text) == n_text
            ]
            instruction_candidates.sort(key=lambda pair: pair[0])
            plan.suspected_rows.append(
                _suspected(
                    plan,
                    TYPE_INSTRUCTION,
                    row.line,
                    "疑似重复：相同说明文字已存在但标题/秒数不同",
                    _summarize_payload(TYPE_INSTRUCTION, payload),
                    _existing_instruction_summary(n_text),
                    instruction_candidates,
                )
            )
            if (TYPE_INSTRUCTION, row.line) not in decisions:
                continue
        counts.valid += 1
        plan.creates[TYPE_INSTRUCTION].append(
            _CreateItem(line=row.line, payload=payload)
        )
        planned_configs.setdefault(n_text, []).append(cfg)
        planned_payloads.setdefault(n_text, payload)


# ── 预览与落库 ───────────────────────────────────────────────────────


def preview_import(
    session: Session, parsed: ParsedFile, editor: User | None = None
) -> QuestionBankImportPreview:
    plan = plan_import(session, parsed, editor=editor)
    sheets = []
    total_valid = 0
    for qtype in QUESTION_BANK_TYPE_ORDER:
        counts = plan.counts[qtype]
        if counts.valid + counts.exact_dup + counts.suspected + counts.invalid == 0:
            continue
        sheets.append(
            QuestionBankTypeCount(
                type=qtype,
                valid_count=counts.valid,
                exact_duplicate_count=counts.exact_dup,
                suspected_duplicate_count=counts.suspected,
                invalid_count=counts.invalid,
                missing_audio_count=counts.missing_audio,
            )
        )
        total_valid += counts.valid
    return QuestionBankImportPreview(
        sheets=sheets,
        issues=plan.issues[:MAX_ISSUES],
        issues_truncated=len(plan.issues) > MAX_ISSUES,
        suspected=plan.suspected_rows[:MAX_SUSPECTED_LISTED],
        suspected_truncated=len(plan.suspected_rows) > MAX_SUSPECTED_LISTED,
        invalid_total=len(plan.error_rows),
        fingerprint=plan_fingerprint(plan),
        new_topics=plan.new_topics,
        unit_fallback_count=plan.unit_fallback_count,
        standalone_sentence_count=plan.standalone_sentence_count,
        total_valid=total_valid,
    )
