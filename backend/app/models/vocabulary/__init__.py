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
    VocabularyChoice as VocabularyChoice,
)
from app.models.vocabulary.assignments import (
    VocabularyMorphSegment as VocabularyMorphSegment,
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
from app.models.vocabulary.farm import (
    BADGE_FARM_FIRST_HARVEST as BADGE_FARM_FIRST_HARVEST,
)
from app.models.vocabulary.farm import (
    BADGE_FARM_HARVEST_7 as BADGE_FARM_HARVEST_7,
)
from app.models.vocabulary.farm import (
    BADGE_SOURCE_CLASSROOM as BADGE_SOURCE_CLASSROOM,
)
from app.models.vocabulary.farm import (
    BADGE_SOURCE_FARM as BADGE_SOURCE_FARM,
)
from app.models.vocabulary.farm import (
    FARM_XP_DAILY_CAP as FARM_XP_DAILY_CAP,
)
from app.models.vocabulary.farm import (
    GROWTH_DAILY_CAP as GROWTH_DAILY_CAP,
)
from app.models.vocabulary.farm import (
    GROWTH_PER_EVENT as GROWTH_PER_EVENT,
)
from app.models.vocabulary.farm import (
    HARVEST_COUNT_BADGE as HARVEST_COUNT_BADGE,
)
from app.models.vocabulary.farm import HARVEST_XP as HARVEST_XP
from app.models.vocabulary.farm import (
    MATURE_POINTS as MATURE_POINTS,
)
from app.models.vocabulary.farm import (
    STAGE_THRESHOLDS as STAGE_THRESHOLDS,
)
from app.models.vocabulary.farm import (
    FarmBadgePublic as FarmBadgePublic,
)
from app.models.vocabulary.farm import (
    FarmHarvestResult as FarmHarvestResult,
)
from app.models.vocabulary.farm import FarmView as FarmView
from app.models.vocabulary.farm import (
    VocabFarmPlot as VocabFarmPlot,
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
from app.models.vocabulary.pk import (
    DEFAULT_PER_QUESTION_SECONDS,
    DEFAULT_QUESTION_COUNT,
    MAX_ACTIVE_MATCHES,
    MAX_PER_QUESTION_SECONDS,
    MAX_QUESTION_COUNT,
    MAX_QUEUE_PLAYERS,
    MIN_PER_QUESTION_SECONDS,
    PK_ANSWER_BASE,
    PK_SPEED_BONUS_MAX,
    PkAnswerRequest,
    PkAnswerResult,
    PkChoice,
    PkLobbyCreate,
    PkLobbyView,
    PkMatchItem,
    PkMatchResult,
    PkMatchView,
    PkMorphSegment,
    PkPlayerSummary,
    VocabPkAnswer,
    VocabPkLobby,
    VocabPkMatch,
    VocabPkPlayer,
)
from app.models.vocabulary.placement import (
    LIMITATION_MATERIAL_LIMITED as LIMITATION_MATERIAL_LIMITED,
)
from app.models.vocabulary.placement import (
    LIMITATION_NONE as LIMITATION_NONE,
)
from app.models.vocabulary.placement import (
    PLACEMENT_BAND_LEVELS as PLACEMENT_BAND_LEVELS,
)
from app.models.vocabulary.placement import (
    PLACEMENT_BAND_ORDER as PLACEMENT_BAND_ORDER,
)
from app.models.vocabulary.placement import (
    PLACEMENT_BAND_PRIMARY_LEVEL as PLACEMENT_BAND_PRIMARY_LEVEL,
)
from app.models.vocabulary.placement import (
    PLACEMENT_DEFAULT_TOTAL as PLACEMENT_DEFAULT_TOTAL,
)
from app.models.vocabulary.placement import (
    PLACEMENT_KIND as PLACEMENT_KIND,
)
from app.models.vocabulary.placement import (
    PLACEMENT_MIN_CHOICE_WORDS as PLACEMENT_MIN_CHOICE_WORDS,
)
from app.models.vocabulary.placement import (
    PLACEMENT_PASS_CORRECT as PLACEMENT_PASS_CORRECT,
)
from app.models.vocabulary.placement import (
    PLACEMENT_START_BAND as PLACEMENT_START_BAND,
)
from app.models.vocabulary.placement import (
    PlacementAnswerRequest as PlacementAnswerRequest,
)
from app.models.vocabulary.placement import (
    PlacementAnswerResponse as PlacementAnswerResponse,
)
from app.models.vocabulary.placement import (
    PlacementChoice as PlacementChoice,
)
from app.models.vocabulary.placement import (
    PlacementHistoryResponse as PlacementHistoryResponse,
)
from app.models.vocabulary.placement import (
    PlacementQuestion as PlacementQuestion,
)
from app.models.vocabulary.placement import (
    PlacementResultPublic as PlacementResultPublic,
)
from app.models.vocabulary.placement import (
    PlacementStartResponse as PlacementStartResponse,
)
from app.models.vocabulary.placement import (
    VocabPlacementResult as VocabPlacementResult,
)
from app.models.vocabulary.reports import (
    VocabularyClassResults as VocabularyClassResults,
)
from app.models.vocabulary.reports import (
    VocabularyPromptTypeStat as VocabularyPromptTypeStat,
)
from app.models.vocabulary.reports import (
    VocabularyRecommendation as VocabularyRecommendation,
)
from app.models.vocabulary.reports import (
    VocabularyRecommendationFocus as VocabularyRecommendationFocus,
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
from app.models.vocabulary.review import (
    CAPABILITY_RECOGNITION as CAPABILITY_RECOGNITION,
)
from app.models.vocabulary.review import (
    CAPABILITY_SPELLING as CAPABILITY_SPELLING,
)
from app.models.vocabulary.review import (
    REVIEW_CAPABILITIES as REVIEW_CAPABILITIES,
)
from app.models.vocabulary.review import (
    VocabularyReviewQueue as VocabularyReviewQueue,
)
from app.models.vocabulary.review import (
    VocabularyReviewQueueItem as VocabularyReviewQueueItem,
)
from app.models.vocabulary.review import (
    VocabularyReviewState as VocabularyReviewState,
)
from app.models.vocabulary.review import (
    VocabularyReviewStats as VocabularyReviewStats,
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
    VocabularyContentReviewAudit as VocabularyContentReviewAudit,
)
from app.models.vocabulary.tables import (
    VocabularySession as VocabularySession,
)
from app.models.vocabulary.tables import (
    VocabularyWord as VocabularyWord,
)
from app.models.vocabulary.words import (
    REVIEW_NOTE_EDITED_AFTER_APPROVAL as REVIEW_NOTE_EDITED_AFTER_APPROVAL,
)
from app.models.vocabulary.words import (
    REVIEW_NOTE_LEGACY as REVIEW_NOTE_LEGACY,
)
from app.models.vocabulary.words import (
    REVIEW_NOTE_LEVEL_CATALOG_VERIFIED as REVIEW_NOTE_LEVEL_CATALOG_VERIFIED,
)
from app.models.vocabulary.words import (
    REVIEW_NOTE_SELF_CONFIRMED as REVIEW_NOTE_SELF_CONFIRMED,
)
from app.models.vocabulary.words import (
    VOCAB_PROMPT_TYPES as VOCAB_PROMPT_TYPES,
)
from app.models.vocabulary.words import (
    VOCAB_REVIEW_STATUSES as VOCAB_REVIEW_STATUSES,
)
from app.models.vocabulary.words import (
    VOCAB_WORD_SOURCES as VOCAB_WORD_SOURCES,
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
    VocabularyContentReviewList as VocabularyContentReviewList,
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
    VocabularyReviewActionRequest as VocabularyReviewActionRequest,
)
from app.models.vocabulary.words import (
    VocabularyReviewActionResult as VocabularyReviewActionResult,
)
from app.models.vocabulary.words import (
    VocabularyReviewAuditItem as VocabularyReviewAuditItem,
)
from app.models.vocabulary.words import (
    VocabularyReviewItem as VocabularyReviewItem,
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
    "VocabularyContentReviewAudit",
    "VocabularyAssignment",
    "VocabularyAssignmentTarget",
    "VocabularySession",
    "VocabularyAnswer",
    "VOCAB_PROMPT_TYPES",
    "VocabularyWordIn",
    "VocabularyWordUpdate",
    "VocabularyWordPublic",
    "VocabularyReviewItem",
    "VocabularyContentReviewList",
    "VocabularyReviewActionRequest",
    "VocabularyReviewActionResult",
    "VocabularyReviewAuditItem",
    "VOCAB_WORD_SOURCES",
    "VOCAB_REVIEW_STATUSES",
    "REVIEW_NOTE_LEGACY",
    "REVIEW_NOTE_SELF_CONFIRMED",
    "REVIEW_NOTE_LEVEL_CATALOG_VERIFIED",
    "REVIEW_NOTE_EDITED_AFTER_APPROVAL",
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
    "VocabularyPromptTypeStat",
    "VocabularyRecommendation",
    "VocabularyRecommendationFocus",
    "VocabularyReviewQueue",
    "VocabularyReviewQueueItem",
    "VocabularyReviewState",
    "VocabularyReviewStats",
    "CAPABILITY_RECOGNITION",
    "CAPABILITY_SPELLING",
    "REVIEW_CAPABILITIES",
    "VocabularyTeacherAssignmentRow",
    "VocabularyWrongWordItem",
    "VocabularyWrongWords",
    "VocabularyChoice",
    "VocabularyMorphSegment",
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
    "VocabPkLobby",
    "VocabPkMatch",
    "VocabPkPlayer",
    "VocabPlacementResult",
    "PLACEMENT_KIND",
    "PLACEMENT_DEFAULT_TOTAL",
    "PLACEMENT_MIN_CHOICE_WORDS",
    "PLACEMENT_START_BAND",
    "PLACEMENT_PASS_CORRECT",
    "PLACEMENT_BAND_ORDER",
    "PLACEMENT_BAND_LEVELS",
    "PLACEMENT_BAND_PRIMARY_LEVEL",
    "LIMITATION_NONE",
    "LIMITATION_MATERIAL_LIMITED",
    "PlacementChoice",
    "PlacementQuestion",
    "PlacementResultPublic",
    "PlacementStartResponse",
    "PlacementAnswerRequest",
    "PlacementAnswerResponse",
    "PlacementHistoryResponse",
    "VocabPkAnswer",
    "VocabFarmPlot",
    "FarmView",
    "FarmHarvestResult",
    "FarmBadgePublic",
    "STAGE_THRESHOLDS",
    "MATURE_POINTS",
    "GROWTH_PER_EVENT",
    "GROWTH_DAILY_CAP",
    "HARVEST_XP",
    "FARM_XP_DAILY_CAP",
    "HARVEST_COUNT_BADGE",
    "BADGE_FARM_FIRST_HARVEST",
    "BADGE_FARM_HARVEST_7",
    "BADGE_SOURCE_FARM",
    "BADGE_SOURCE_CLASSROOM",
    "PkLobbyCreate",
    "PkLobbyView",
    "PkPlayerSummary",
    "PkChoice",
    "PkMorphSegment",
    "PkMatchItem",
    "PkMatchResult",
    "PkMatchView",
    "PkAnswerRequest",
    "PkAnswerResult",
    "MAX_QUEUE_PLAYERS",
    "MAX_ACTIVE_MATCHES",
    "DEFAULT_QUESTION_COUNT",
    "DEFAULT_PER_QUESTION_SECONDS",
    "MAX_QUESTION_COUNT",
    "MIN_PER_QUESTION_SECONDS",
    "MAX_PER_QUESTION_SECONDS",
    "PK_ANSWER_BASE",
    "PK_SPEED_BONUS_MAX",
]
