"""词汇模型包对外门面：`from app.models.vocabulary import X` 的兼容入口。

拆分（2026-11-07）：表在 tables.py，其余按域分文件；本文件只做再导出，
保证既有 `from app.models.vocabulary import ...` 与 `from app.models import ...` 不变。
"""

from app.models.vocabulary.ai import (
    VOCAB_AI_DRAFT_MAX as VOCAB_AI_DRAFT_MAX,
)
from app.models.vocabulary.ai import (
    VOCAB_AI_HINT_MAX as VOCAB_AI_HINT_MAX,
)
from app.models.vocabulary.ai import (
    VOCAB_AI_RATE_LIMIT as VOCAB_AI_RATE_LIMIT,
)
from app.models.vocabulary.ai import (
    VOCAB_AI_RATE_WINDOW_S as VOCAB_AI_RATE_WINDOW_S,
)
from app.models.vocabulary.ai import (
    VOCAB_AI_THEME_MAX as VOCAB_AI_THEME_MAX,
)
from app.models.vocabulary.ai import (
    VocabularyAiCache as VocabularyAiCache,
)
from app.models.vocabulary.ai import (
    VocabularyAiExplanationRequest as VocabularyAiExplanationRequest,
)
from app.models.vocabulary.ai import (
    VocabularyAiInsightScope as VocabularyAiInsightScope,
)
from app.models.vocabulary.ai import (
    VocabularyAiOverallInsight as VocabularyAiOverallInsight,
)
from app.models.vocabulary.ai import (
    VocabularyAiOverallInsightRequest as VocabularyAiOverallInsightRequest,
)
from app.models.vocabulary.ai import (
    VocabularyAiSessionInsight as VocabularyAiSessionInsight,
)
from app.models.vocabulary.ai import (
    VocabularyAiSessionInsightRequest as VocabularyAiSessionInsightRequest,
)
from app.models.vocabulary.ai import (
    VocabularyAiWeakWord as VocabularyAiWeakWord,
)
from app.models.vocabulary.ai import (
    VocabularyAiWordDraft as VocabularyAiWordDraft,
)
from app.models.vocabulary.ai import (
    VocabularyAiWordDraftImportRequest as VocabularyAiWordDraftImportRequest,
)
from app.models.vocabulary.ai import (
    VocabularyAiWordDraftImportResult as VocabularyAiWordDraftImportResult,
)
from app.models.vocabulary.ai import (
    VocabularyAiWordDraftsRequest as VocabularyAiWordDraftsRequest,
)
from app.models.vocabulary.ai import (
    VocabularyAiWordDraftsResponse as VocabularyAiWordDraftsResponse,
)
from app.models.vocabulary.ai import (
    VocabularyAiWordExplanation as VocabularyAiWordExplanation,
)
from app.models.vocabulary.assignments import (
    VocabularyAssignmentCreate as VocabularyAssignmentCreate,
)
from app.models.vocabulary.assignments import (
    VocabularyAssignmentPublic as VocabularyAssignmentPublic,
)
from app.models.vocabulary.assignments import (
    VocabularyQuizState as VocabularyQuizState,
)
from app.models.vocabulary.assignments import (
    VocabularyRoundSummaryRow as VocabularyRoundSummaryRow,
)
from app.models.vocabulary.assignments import (
    VocabularyStudentAssignment as VocabularyStudentAssignment,
)
from app.models.vocabulary.assignments import (
    VocabularyTodayItem as VocabularyTodayItem,
)
from app.models.vocabulary.assignments import (
    VocabularyTodayPlan as VocabularyTodayPlan,
)
from app.models.vocabulary.levels import (
    VOCAB_LEVEL_IMPORT_MAX_ROWS as VOCAB_LEVEL_IMPORT_MAX_ROWS,
)
from app.models.vocabulary.levels import (
    VocabularyLevelEntry as VocabularyLevelEntry,
)
from app.models.vocabulary.levels import (
    VocabularyLevelEntryPublic as VocabularyLevelEntryPublic,
)
from app.models.vocabulary.levels import (
    VocabularyLevelEntryUpdate as VocabularyLevelEntryUpdate,
)
from app.models.vocabulary.levels import (
    VocabularyLevelImportIssue as VocabularyLevelImportIssue,
)
from app.models.vocabulary.levels import (
    VocabularyLevelImportPreview as VocabularyLevelImportPreview,
)
from app.models.vocabulary.levels import (
    VocabularyLevelImportResult as VocabularyLevelImportResult,
)
from app.models.vocabulary.levels import (
    VocabularyLevelLevelCount as VocabularyLevelLevelCount,
)
from app.models.vocabulary.levels import (
    VocabularyLevelStats as VocabularyLevelStats,
)
from app.models.vocabulary.levels import (
    VocabularyLevelWordInfo as VocabularyLevelWordInfo,
)
from app.models.vocabulary.levels import (
    effective_vocab_level as effective_vocab_level,
)
from app.models.vocabulary.reports import (
    VocabularyClassResults as VocabularyClassResults,
)
from app.models.vocabulary.reports import (
    VocabularyStudentResultRow as VocabularyStudentResultRow,
)
from app.models.vocabulary.reports import (
    VocabularyStudentRoundRow as VocabularyStudentRoundRow,
)
from app.models.vocabulary.reports import (
    VocabularyTeacherAssignmentRow as VocabularyTeacherAssignmentRow,
)
from app.models.vocabulary.reports import (
    VocabularyWordMisspelling as VocabularyWordMisspelling,
)
from app.models.vocabulary.reports import (
    VocabularyWordStatRow as VocabularyWordStatRow,
)
from app.models.vocabulary.reports import (
    VocabularyWrongWordItem as VocabularyWrongWordItem,
)
from app.models.vocabulary.reports import (
    VocabularyWrongWords as VocabularyWrongWords,
)
from app.models.vocabulary.self_practice import (
    SELF_PRACTICE_DEFAULT_WORDS as SELF_PRACTICE_DEFAULT_WORDS,
)
from app.models.vocabulary.self_practice import (
    SELF_PRACTICE_MAX_WORDS as SELF_PRACTICE_MAX_WORDS,
)
from app.models.vocabulary.self_practice import (
    SELF_PRACTICE_MIX_WRONG_RATIO as SELF_PRACTICE_MIX_WRONG_RATIO,
)
from app.models.vocabulary.self_practice import (
    VocabularyStudentHistory as VocabularyStudentHistory,
)
from app.models.vocabulary.self_practice import (
    VocabularyStudentHistoryRow as VocabularyStudentHistoryRow,
)
from app.models.vocabulary.self_practice import (
    VocabularyStudentItem as VocabularyStudentItem,
)
from app.models.vocabulary.self_practice import (
    VocabularyStudentPlan as VocabularyStudentPlan,
)
from app.models.vocabulary.self_practice import (
    VocabularyStudentSessionCreate as VocabularyStudentSessionCreate,
)
from app.models.vocabulary.self_practice import (
    VocabularyStudentSessionCreated as VocabularyStudentSessionCreated,
)
from app.models.vocabulary.sessions import (
    VocabularyAnswerRequest as VocabularyAnswerRequest,
)
from app.models.vocabulary.sessions import (
    VocabularyAnswerResult as VocabularyAnswerResult,
)
from app.models.vocabulary.sessions import (
    VocabularyQuizAnswerReceipt as VocabularyQuizAnswerReceipt,
)
from app.models.vocabulary.sessions import (
    VocabularySessionCreate as VocabularySessionCreate,
)
from app.models.vocabulary.tables import (
    VocabularyAnswer as VocabularyAnswer,
)
from app.models.vocabulary.tables import (
    VocabularyAssignment as VocabularyAssignment,
)
from app.models.vocabulary.tables import (
    VocabularyAssignmentTarget as VocabularyAssignmentTarget,
)
from app.models.vocabulary.tables import (
    VocabularyBook as VocabularyBook,
)
from app.models.vocabulary.tables import (
    VocabularyBookItem as VocabularyBookItem,
)
from app.models.vocabulary.tables import (
    VocabularySession as VocabularySession,
)
from app.models.vocabulary.tables import (
    VocabularyWord as VocabularyWord,
)
from app.models.vocabulary.words import (
    VOCAB_PROMPT_TYPES as VOCAB_PROMPT_TYPES,
)
from app.models.vocabulary.words import (
    VocabularyBookCreate as VocabularyBookCreate,
)
from app.models.vocabulary.words import (
    VocabularyBookDetail as VocabularyBookDetail,
)
from app.models.vocabulary.words import (
    VocabularyBookPublic as VocabularyBookPublic,
)
from app.models.vocabulary.words import (
    VocabularyBookUpdate as VocabularyBookUpdate,
)
from app.models.vocabulary.words import (
    VocabularyImportIssue as VocabularyImportIssue,
)
from app.models.vocabulary.words import (
    VocabularyImportPreview as VocabularyImportPreview,
)
from app.models.vocabulary.words import (
    VocabularyImportRow as VocabularyImportRow,
)
from app.models.vocabulary.words import (
    VocabularyWordIn as VocabularyWordIn,
)
from app.models.vocabulary.words import (
    VocabularyWordPublic as VocabularyWordPublic,
)
from app.models.vocabulary.words import (
    VocabularyWordUpdate as VocabularyWordUpdate,
)

__all__ = [
    "VocabularyWord",
    "VocabularyBook",
    "VocabularyBookItem",
    "VocabularyAssignment",
    "VocabularyAssignmentTarget",
    "VocabularySession",
    "VocabularyAnswer",
    "VOCAB_PROMPT_TYPES",
    "VocabularyWordIn",
    "VocabularyWordUpdate",
    "VocabularyWordPublic",
    "VocabularyBookCreate",
    "VocabularyBookUpdate",
    "VocabularyBookPublic",
    "VocabularyBookDetail",
    "VocabularyImportRow",
    "VocabularyImportIssue",
    "VocabularyImportPreview",
    "VocabularyAssignmentCreate",
    "VocabularyAssignmentPublic",
    "VocabularyQuizState",
    "VocabularyTodayItem",
    "VocabularyStudentAssignment",
    "VocabularyRoundSummaryRow",
    "VocabularyTodayPlan",
    "VocabularySessionCreate",
    "VocabularyAnswerRequest",
    "VocabularyAnswerResult",
    "VocabularyQuizAnswerReceipt",
    "VocabularyStudentRoundRow",
    "VocabularyStudentResultRow",
    "VocabularyWordMisspelling",
    "VocabularyWordStatRow",
    "VocabularyClassResults",
    "VocabularyTeacherAssignmentRow",
    "VocabularyWrongWordItem",
    "VocabularyWrongWords",
    "VOCAB_AI_DRAFT_MAX",
    "VOCAB_AI_THEME_MAX",
    "VOCAB_AI_HINT_MAX",
    "VOCAB_AI_RATE_LIMIT",
    "VOCAB_AI_RATE_WINDOW_S",
    "VocabularyAiCache",
    "VocabularyAiWordDraft",
    "VocabularyAiWordDraftsRequest",
    "VocabularyAiWordDraftsResponse",
    "VocabularyAiWordDraftImportRequest",
    "VocabularyAiWordDraftImportResult",
    "VocabularyAiWordExplanation",
    "VocabularyAiExplanationRequest",
    "VocabularyAiWeakWord",
    "VocabularyAiSessionInsightRequest",
    "VocabularyAiInsightScope",
    "VocabularyAiSessionInsight",
    "VocabularyAiOverallInsightRequest",
    "VocabularyAiOverallInsight",
    "SELF_PRACTICE_DEFAULT_WORDS",
    "SELF_PRACTICE_MAX_WORDS",
    "SELF_PRACTICE_MIX_WRONG_RATIO",
    "VocabularyStudentSessionCreate",
    "VocabularyStudentSessionCreated",
    "VocabularyStudentItem",
    "VocabularyStudentPlan",
    "VocabularyStudentHistoryRow",
    "VocabularyStudentHistory",
    "effective_vocab_level",
    "VocabularyLevelEntry",
    "VOCAB_LEVEL_IMPORT_MAX_ROWS",
    "VocabularyLevelEntryPublic",
    "VocabularyLevelEntryUpdate",
    "VocabularyLevelLevelCount",
    "VocabularyLevelStats",
    "VocabularyLevelImportIssue",
    "VocabularyLevelImportPreview",
    "VocabularyLevelImportResult",
    "VocabularyLevelWordInfo",
]
