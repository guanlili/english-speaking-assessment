import { Badge } from "@/components/ui/badge"
import { useI18n } from "@/lib/i18n"
import {
  CEFR_BAND_LABELS,
  type CefrBand,
  EXAM_TAG_LABELS,
  type VocabExamTag,
} from "@/lib/terms"

function isExamTag(value: string): value is VocabExamTag {
  return value in EXAM_TAG_LABELS
}

function isCefrBand(value: string): value is CefrBand {
  return value in CEFR_BAND_LABELS
}

/** 考试标签徽标（SAT/ACT/GRE/CET4/IELTS/TOEFL）；非法取值回落为原始代码。 */
export function ExamTagBadge({ tag }: { tag: string }) {
  const { t } = useI18n()
  if (!isExamTag(tag)) return null
  return (
    <Badge variant="outline" className="text-xs font-medium">
      {t(EXAM_TAG_LABELS[tag])}
    </Badge>
  )
}

/**
 * CEFR 档位徽标（A1–C2）。
 * compact=true 时只显示档位代码（学生侧只读标签）；档位只是词条内容标签，
 * 不构成对学生的能力评定。
 */
export function CefrBandBadge({
  band,
  compact = false,
}: {
  band: string | null | undefined
  compact?: boolean
}) {
  const { t } = useI18n()
  if (!band || !isCefrBand(band)) return null
  return (
    <Badge variant="secondary" className="text-xs font-medium">
      {compact ? band : t(CEFR_BAND_LABELS[band])}
    </Badge>
  )
}

/**
 * 词条标签集合：考试标签 + CEFR 档位。
 * showExamTags=false 时只展示 CEFR（学生侧口径：不下发/不展示考试标签）。
 */
export function WordTagBadges({
  exam_tags,
  cefr_band,
  showExamTags = true,
  compact = false,
}: {
  exam_tags?: readonly string[] | null
  cefr_band?: string | null
  showExamTags?: boolean
  compact?: boolean
}) {
  const tags = Array.isArray(exam_tags) ? exam_tags : []
  if (tags.length === 0 && !cefr_band) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {showExamTags && tags.map((tag) => <ExamTagBadge key={tag} tag={tag} />)}
      <CefrBandBadge band={cefr_band} compact={compact} />
    </div>
  )
}
