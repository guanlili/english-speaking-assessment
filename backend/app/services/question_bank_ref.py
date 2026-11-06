"""题库导入查重引用：库内参照快照（_Ref）与按归一键匹配存量行。"""

import uuid
from dataclasses import (
    dataclass,
)
from typing import (
    Any,
)

from sqlalchemy import (
    func,
)
from sqlmodel import (
    Session,
    col,
    select,
)

from app.models import (
    Instruction,
    Passage,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    Unit,
)
from app.services import (
    content_dedup,
)
from app.services.question_bank_parse import (
    BUILDERS,
    ParsedFile,
    _RowError,
)
from app.services.question_bank_spec import (
    QUESTION_BANK_TYPE_ORDER,
    TYPE_INSTRUCTION,
    TYPE_PASSAGE,
    TYPE_QUESTION,
    TYPE_REPEAT,
    _norm_text,
)

# ── 库内参照与查重计划 ───────────────────────────────────────────────


@dataclass
class _Ref:
    """查重与兜底解析需要的库内参照（一次性加载；题库规模下全表可控）。"""

    units_by_norm: dict[str, list[Unit]]
    root_passages_by_norm: dict[str, list[Passage]]
    passage_exact: dict[tuple[str, str], list[tuple[Any, ...]]]
    passage_texts: set[str]
    # 主题匹配：精确优先。规范化字典允许 Travel/travel 并存（后者不覆盖
    # 前者）；规范化命中多个时由调用方报行级错误，绝不静默选一个
    scenarios_by_exact: dict[str, Scenario]
    scenarios_by_norm: dict[str, list[Scenario]]
    # 查重按对象身份（scenario_id），不按主题名——travel/Travel 是两个主题，
    # 各自持有同题不是完全重复（评审 P2）
    question_exact: dict[tuple[uuid.UUID, str], list[tuple[Any, ...]]]
    question_texts: dict[str, set[uuid.UUID]]
    # 复述句同理：挂靠身份是 passage_id（同名根篇/旧子篇是不同记录）
    sentence_configs: dict[str, list[tuple[uuid.UUID | None, tuple[Any, ...]]]]
    instruction_configs: dict[str, list[tuple[Any, ...]]]
    # 疑似重复对照用：库内候选行对象（键与上面查重索引一致）
    unit_titles: dict[uuid.UUID, str]
    passage_titles: dict[uuid.UUID, str]
    scenario_topics: dict[uuid.UUID, str]
    passages_by_key: dict[tuple[str, str], list[Passage]]
    sentences_by_key: dict[str, list[RepeatSentence]]
    questions_by_key: dict[tuple[uuid.UUID, str], list[ScenarioQuestion]]
    instructions_all: list[Instruction]
    existing_slugs: set[str]
    max_question_order: dict[uuid.UUID, int]
    max_sentence_order_by_passage: dict[uuid.UUID, int]
    max_sentence_order_global: int


def _matching_ids(
    session: Session,
    model: Any,
    text_attr: Any,
    hash_attr: Any,
    wanted: set[str],
    *conditions: Any,
) -> list[uuid.UUID]:
    """按归一键匹配存量行：优先走预计算哈希索引（dedup_*_hash 列）。

    哈希列由 services/content_dedup.py 的 flush 钩子维护、迁移回填存量；
    NULL 行（理论仅迁移前残留）回退流式拉原文做 Python 归一——NFKC/
    casefold/Unicode 空白语义 Python 是唯一权威，不用数据库 lower 近似。
    """
    if not wanted:
        return []
    wanted_hashes = [content_dedup.hash_norm(w) for w in wanted]
    matched = list(
        session.exec(
            select(model.id).where(hash_attr.in_(wanted_hashes), *conditions)
        ).all()
    )
    legacy = session.exec(
        select(model.id, text_attr)
        .where(col(hash_attr).is_(None), *conditions)
        .execution_options(yield_per=256)
    )
    try:
        matched.extend(
            row_id for row_id, value in legacy if _norm_text(value or "") in wanted
        )
    finally:
        legacy.close()
    return matched


@dataclass(frozen=True)
class _Candidates:
    """查重候选集合：一次收集，索引构建阶段只读。"""

    passage_ids: set[uuid.UUID]
    scenario_ids: set[uuid.UUID]
    units: list[Unit]
    root_passages: list[Passage]
    scenarios: list[Scenario]
    questions: list[ScenarioQuestion]
    sentences: list[RepeatSentence]
    instructions: list[Instruction]
    passage_title_rows: list[tuple[uuid.UUID, str]]


def _load_reference(session: Session, parsed: ParsedFile) -> _Ref:
    payloads: dict[str, list[dict[str, Any]]] = {
        kind: [] for kind in QUESTION_BANK_TYPE_ORDER
    }
    for row in parsed.rows:
        try:
            payloads[row.qtype].append(BUILDERS[row.qtype](row.cells))
        except _RowError:
            continue  # 规划阶段仍返回原行错误；无效行不需要读取候选
    candidates = _collect_candidates(session, payloads)
    return _build_ref(session, payloads, candidates)


def _collect_candidates(
    session: Session, payloads: dict[str, list[dict[str, Any]]]
) -> _Candidates:
    """按归一键批量捞库内候选（标题/正文/主题/题干各走一次索引查询）。"""
    passage_payloads = payloads[TYPE_PASSAGE]
    repeat_payloads = payloads[TYPE_REPEAT]
    question_payloads = payloads[TYPE_QUESTION]
    instruction_payloads = payloads[TYPE_INSTRUCTION]
    titles = {_norm_text(p["title"]) for p in passage_payloads}
    titles.update(
        _norm_text(p["passage_title"]) for p in repeat_payloads if p["passage_title"]
    )
    passage_ids = set(
        _matching_ids(
            session,
            Passage,
            Passage.title,
            Passage.dedup_title_hash,
            titles,
            col(Passage.parent_passage_id).is_(None),
        )
    )
    passage_ids.update(
        _matching_ids(
            session,
            Passage,
            Passage.text,
            Passage.dedup_text_hash,
            {_norm_text(p["text"]) for p in passage_payloads},
            col(Passage.parent_passage_id).is_(None),
        )
    )
    units_wanted = {
        _norm_text(p["unit_title"]) for p in passage_payloads if p.get("unit_title")
    }
    unit_ids = _matching_ids(
        session, Unit, Unit.title, Unit.dedup_title_hash, units_wanted
    )
    root_passages = (
        list(
            session.exec(select(Passage).where(col(Passage.id).in_(passage_ids))).all()
        )
        if passage_ids
        else []
    )
    # 已有候选挂靠的单元影响完全重复/指纹，必须把它们也补齐。
    unit_ids.extend(p.unit_id for p in root_passages if p.unit_id is not None)
    units = (
        list(session.exec(select(Unit).where(col(Unit.id).in_(unit_ids))).all())
        if unit_ids
        else []
    )
    scenario_ids = set(
        _matching_ids(
            session,
            Scenario,
            Scenario.topic,
            Scenario.dedup_topic_hash,
            {_norm_text(p["topic"]) for p in question_payloads},
        )
    )
    question_ids = _matching_ids(
        session,
        ScenarioQuestion,
        ScenarioQuestion.text,
        ScenarioQuestion.dedup_text_hash,
        {_norm_text(p["text"]) for p in question_payloads},
    )
    questions = (
        list(
            session.exec(
                select(ScenarioQuestion).where(
                    col(ScenarioQuestion.id).in_(question_ids)
                )
            ).all()
        )
        if question_ids
        else []
    )
    scenario_ids.update(q.scenario_id for q in questions)
    scenarios = (
        list(
            session.exec(
                select(Scenario).where(col(Scenario.id).in_(scenario_ids))
            ).all()
        )
        if scenario_ids
        else []
    )
    sentence_ids = _matching_ids(
        session,
        RepeatSentence,
        RepeatSentence.text,
        RepeatSentence.dedup_text_hash,
        {_norm_text(p["text"]) for p in repeat_payloads},
    )
    sentences = (
        list(
            session.exec(
                select(RepeatSentence).where(col(RepeatSentence.id).in_(sentence_ids))
            ).all()
        )
        if sentence_ids
        else []
    )
    instruction_ids = _matching_ids(
        session,
        Instruction,
        Instruction.text,
        Instruction.dedup_text_hash,
        {_norm_text(p["text"]) for p in instruction_payloads},
    )
    instructions = (
        list(
            session.exec(
                select(Instruction).where(col(Instruction.id).in_(instruction_ids))
            ).all()
        )
        if instruction_ids
        else []
    )
    linked_ids = passage_ids | {
        s.passage_id for s in sentences if s.passage_id is not None
    }
    passage_title_rows = (
        session.exec(
            select(Passage.id, Passage.title).where(col(Passage.id).in_(linked_ids))
        ).all()
        if linked_ids
        else []
    )
    return _Candidates(
        passage_ids=passage_ids,
        scenario_ids=scenario_ids,
        units=units,
        root_passages=root_passages,
        scenarios=scenarios,
        questions=questions,
        sentences=sentences,
        instructions=instructions,
        passage_title_rows=list(passage_title_rows),
    )


def _build_ref(
    session: Session,
    payloads: dict[str, list[dict[str, Any]]],
    candidates: _Candidates,
) -> _Ref:
    """把候选集合摊成各类查重索引（含序号上限与现有 slug）。"""
    passage_payloads = payloads[TYPE_PASSAGE]
    repeat_payloads = payloads[TYPE_REPEAT]
    question_payloads = payloads[TYPE_QUESTION]
    passage_ids = candidates.passage_ids
    scenario_ids = candidates.scenario_ids
    units = candidates.units
    root_passages = candidates.root_passages
    scenarios = candidates.scenarios
    questions = candidates.questions
    sentences = candidates.sentences
    instructions = candidates.instructions
    passage_title_rows = candidates.passage_title_rows
    units_by_norm: dict[str, list[Unit]] = {}
    for unit in units:
        units_by_norm.setdefault(_norm_text(unit.title), []).append(unit)

    root_passages_by_norm: dict[str, list[Passage]] = {}
    for passage in root_passages:
        root_passages_by_norm.setdefault(_norm_text(passage.title), []).append(passage)

    unit_titles = {u.id: u.title for u in units}
    passage_exact: dict[tuple[str, str], list[tuple[Any, ...]]] = {}
    passage_texts: set[str] = set()
    for passage in root_passages:
        key = (_norm_text(passage.title), _norm_text(passage.text))
        cfg = (
            _norm_text(passage.translation or ""),
            passage.cefr_band,
            passage.suggested_seconds,
            passage.is_active,
            _norm_text(unit_titles.get(passage.unit_id, "")) if passage.unit_id else "",
            _norm_text(passage.topic or ""),
            passage.audio_url or "",
        )
        passage_exact.setdefault(key, []).append(cfg)
        passage_texts.add(key[1])

    scenarios_by_exact = {s.topic: s for s in scenarios}
    scenarios_by_norm: dict[str, list[Scenario]] = {}
    for s in scenarios:
        scenarios_by_norm.setdefault(_norm_text(s.topic), []).append(s)
    question_exact: dict[tuple[uuid.UUID, str], list[tuple[Any, ...]]] = {}
    question_texts: dict[str, set[uuid.UUID]] = {}
    for question in questions:
        # 键是 (scenario_id, 规范化题干)：主题身份进键，cfg 不再携带主题名
        key = (question.scenario_id, _norm_text(question.text))
        cfg = (
            _norm_text(question.translation or ""),
            question.suggested_seconds,
            question.exam_kind or "",
            question.exam_level or "",
            tuple(question.cue_card_bullets or ()),
            question.prep_seconds or 0,
            question.audio_url or "",
        )
        question_exact.setdefault(key, []).append(cfg)
        question_texts.setdefault(_norm_text(question.text), set()).add(
            question.scenario_id
        )

    # (passage_id 或 None=独立句, cfg)：挂靠身份与配置分开存，比较时按身份过滤
    sentence_configs: dict[str, list[tuple[uuid.UUID | None, tuple[Any, ...]]]] = {}
    for sentence in sentences:
        cfg = (
            _norm_text(sentence.translation or ""),
            sentence.suggested_seconds,
            sentence.replay_limit,
            sentence.exam_kind or "",
            sentence.exam_level or "",
            sentence.audio_url or "",
        )
        sentence_configs.setdefault(_norm_text(sentence.text), []).append(
            (sentence.passage_id, cfg)
        )

    instruction_configs: dict[str, list[tuple[Any, ...]]] = {}
    for ins in instructions:
        cfg = (_norm_text(ins.title or ""), ins.suggested_seconds)
        instruction_configs.setdefault(_norm_text(ins.text), []).append(cfg)

    # 疑似对照行对象索引（与查重索引同键）
    passage_titles = dict(passage_title_rows)
    scenario_topics = {s_.id: s_.topic for s_ in scenarios}
    passages_by_key: dict[tuple[str, str], list[Passage]] = {}
    for passage in root_passages:
        passages_by_key.setdefault(
            (_norm_text(passage.title), _norm_text(passage.text)), []
        ).append(passage)
    sentences_by_key: dict[str, list[RepeatSentence]] = {}
    for sentence in sentences:
        sentences_by_key.setdefault(_norm_text(sentence.text), []).append(sentence)
    questions_by_key: dict[tuple[uuid.UUID, str], list[ScenarioQuestion]] = {}
    for question in questions:
        questions_by_key.setdefault(
            (question.scenario_id, _norm_text(question.text)), []
        ).append(question)

    max_question_order = (
        dict(
            session.exec(
                select(
                    ScenarioQuestion.scenario_id, func.max(ScenarioQuestion.order_index)
                )
                .where(col(ScenarioQuestion.scenario_id).in_(scenario_ids))
                .group_by(col(ScenarioQuestion.scenario_id))
            ).all()
        )
        if question_payloads
        else {}
    )
    max_by_passage = (
        dict(
            session.exec(
                select(RepeatSentence.passage_id, func.max(RepeatSentence.order_index))
                .where(col(RepeatSentence.passage_id).in_(passage_ids))
                .group_by(col(RepeatSentence.passage_id))
            ).all()
        )
        if repeat_payloads
        else {}
    )
    global_max = (
        session.exec(select(func.max(RepeatSentence.order_index))).one() or 0
        if repeat_payloads
        else 0
    )
    existing_slugs = (
        set(session.exec(select(Passage.slug)).all()) if passage_payloads else set()
    )

    return _Ref(
        units_by_norm=units_by_norm,
        root_passages_by_norm=root_passages_by_norm,
        passage_exact=passage_exact,
        passage_texts=passage_texts,
        scenarios_by_exact=scenarios_by_exact,
        scenarios_by_norm=scenarios_by_norm,
        question_exact=question_exact,
        question_texts=question_texts,
        sentence_configs=sentence_configs,
        instruction_configs=instruction_configs,
        unit_titles=unit_titles,
        passage_titles=passage_titles,
        scenario_topics=scenario_topics,
        passages_by_key=passages_by_key,
        sentences_by_key=sentences_by_key,
        questions_by_key=questions_by_key,
        instructions_all=list(instructions),
        existing_slugs=existing_slugs,
        max_question_order=max_question_order,
        max_sentence_order_by_passage=max_by_passage,
        max_sentence_order_global=global_max,
    )
