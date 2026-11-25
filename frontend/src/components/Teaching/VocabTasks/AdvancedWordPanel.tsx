import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Send } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import {
  ApiError,
  VocabLevelsService,
  type VocabularyWordPublic,
} from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { WordTagBadges } from "@/components/Vocabulary/WordTagBadges"
import { useI18n } from "@/lib/i18n"
import {
  CEFR_BAND_LABELS,
  CEFR_BANDS,
  type CefrBand,
  EXAM_TAG_LABELS,
  VOCAB_EXAM_TAGS,
  type VocabExamTag,
} from "@/lib/terms"
import { CODE_NOT_APPROVED, parseDetailCount } from "@/lib/vocabContentReview"
import { describeLicensePublishError } from "@/lib/vocabGovernance"

type TargetBook = {
  id: string
  title: string
  scope?: string | null
  word_count?: number | null
}

/**
 * 扩展区 · 高级备考词（#517）。
 *
 * 独立分区浏览 SAT/ACT/GRE 等高级词，勾选后转入教学词库。转入门禁与发布
 * 路径同口径：服务端强制审核（approved）与授权校验，前端只做选择与提示，
 * 不绕过 pending/approved 或 textbook/licensed 授权。CEFR 只是词条内容标签，
 * 不在学生侧做等级评定。
 */
export function AdvancedWordPanel({
  classroomId,
  books,
}: {
  classroomId: string | null
  books: TargetBook[]
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const [examTag, setExamTag] = useState<string>("all")
  const [cefrBand, setCefrBand] = useState<string>("all")
  const [headword, setHeadword] = useState("")
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [targetBookId, setTargetBookId] = useState<string>("")
  const [newBookTitle, setNewBookTitle] = useState("")

  const advancedQuery = useQuery({
    queryKey: ["vocab-teacher", "advanced-words", examTag, cefrBand, headword],
    queryFn: () =>
      VocabLevelsService.listAdvancedWords({
        exam_tag: examTag === "all" ? null : examTag,
        cefr_band: cefrBand === "all" ? null : cefrBand,
        headword: headword.trim() || null,
        limit: 500,
      }),
  })
  const words: VocabularyWordPublic[] = advancedQuery.data ?? []

  const toggleWord = (id: string, checked: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })

  const toggleAll = (checked: boolean) =>
    setSelected(checked ? new Set(words.map((w) => w.id)) : new Set())

  const targetIsNewBook = targetBookId === ""

  const transfer = useMutation({
    mutationFn: () =>
      VocabLevelsService.transferAdvancedWords({
        vocabularyAdvancedTransferRequest: {
          word_ids: Array.from(selected),
          book_id: targetIsNewBook ? null : targetBookId,
          classroom_id: targetIsNewBook ? classroomId : null,
          new_book_title: targetIsNewBook ? newBookTitle.trim() || null : null,
        },
      }),
    onSuccess: (data) => {
      toast.success(
        t({
          zh: `已转入 ${data.created_count ?? 0} 个高级备考词（跳过 ${data.skipped_existing ?? 0} 个已有词）。`,
          en: `Transferred ${data.created_count ?? 0} advanced words (${data.skipped_existing ?? 0} existing skipped).`,
        }),
      )
      setSelected(new Set())
      queryClient.invalidateQueries({ queryKey: ["vocab-teacher", "books"] })
      queryClient.invalidateQueries({
        queryKey: ["vocab-teacher", "advanced-words"],
      })
    },
    onError: (error) => {
      if (!(error instanceof ApiError)) {
        toast.error(
          t({
            zh: "转入失败，请检查网络后重试。",
            en: "Transfer failed — check your connection and retry.",
          }),
        )
        return
      }
      const detail =
        typeof error.body === "object" && error.body !== null
          ? ((error.body as { detail?: unknown }).detail ?? error.message)
          : error.message
      if (error.status === 422) {
        const licenseError = describeLicensePublishError(detail)
        if (licenseError) {
          toast.error(t(licenseError))
          return
        }
        const notApproved = parseDetailCount(detail, CODE_NOT_APPROVED)
        if (notApproved !== null) {
          toast.error(
            t({
              zh: `有 ${notApproved} 个词条尚未通过审核，不能转入；请先在「词库审核」中通过。`,
              en: `${notApproved} selected words are not approved yet — approve them in Review before transferring.`,
            }),
          )
          return
        }
        toast.error(
          t({
            zh: "转入被拒绝：词条不可用或不符合扩展区口径。",
            en: "Transfer rejected: words are unavailable or don't match the advanced source.",
          }),
        )
        return
      }
      if (error.status === 403) {
        toast.error(
          t({
            zh: "没有权限把这些词条转入目标词库。",
            en: "You don't have permission to transfer these words to the target book.",
          }),
        )
        return
      }
      toast.error(
        t({ zh: "转入失败，请重试。", en: "Transfer failed — please retry." }),
      )
    },
  })

  const canTransfer =
    selected.size > 0 &&
    !transfer.isPending &&
    (targetIsNewBook ? classroomId !== null : true)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t({ zh: "扩展区 · 高级备考词", en: "Advanced Exam Prep" })}
        </CardTitle>
        <CardDescription>
          {t({
            zh: "浏览 SAT/ACT/GRE 等高级备考词，勾选后转入教学词库。转入需通过审核与授权校验；CEFR 档位是词条内容标签，不代表学生水平。",
            en: "Browse advanced SAT/ACT/GRE words and transfer checked ones into a teaching book. Transfer passes the same review and license checks; the CEFR band labels the word only — it is not a student level.",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label={t({ zh: "按考试标签筛选", en: "Filter by exam tag" })}
            value={examTag}
            onChange={(event) => {
              setExamTag(event.target.value)
              setSelected(new Set())
            }}
            className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
          >
            <option value="all">
              {t({ zh: "全部考试", en: "All exams" })}
            </option>
            {VOCAB_EXAM_TAGS.map((tag: VocabExamTag) => (
              <option key={tag} value={tag}>
                {t(EXAM_TAG_LABELS[tag])}
              </option>
            ))}
          </select>
          <select
            aria-label={t({
              zh: "按 CEFR 档位筛选",
              en: "Filter by CEFR band",
            })}
            value={cefrBand}
            onChange={(event) => {
              setCefrBand(event.target.value)
              setSelected(new Set())
            }}
            className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
          >
            <option value="all">
              {t({ zh: "全部档位", en: "All bands" })}
            </option>
            {CEFR_BANDS.map((band: CefrBand) => (
              <option key={band} value={band}>
                {t(CEFR_BAND_LABELS[band])}
              </option>
            ))}
          </select>
          <Input
            value={headword}
            onChange={(event) => setHeadword(event.target.value)}
            placeholder={t({ zh: "按词头搜索…", en: "Search headword…" })}
            aria-label={t({ zh: "按词头搜索", en: "Search by headword" })}
            className="h-11 max-w-48 text-base"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">
            {t({ zh: "转入到", en: "Transfer to" })}
          </span>
          <select
            aria-label={t({ zh: "选择目标词库", en: "Choose target book" })}
            value={targetBookId}
            onChange={(event) => setTargetBookId(event.target.value)}
            className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
          >
            <option value="">
              {t({ zh: "新建班级词库", en: "New classroom book" })}
            </option>
            {books.map((book) => (
              <option key={book.id} value={book.id}>
                {book.title}（{book.word_count ?? 0}{" "}
                {t({ zh: "词", en: "words" })}）
              </option>
            ))}
          </select>
          {targetIsNewBook && (
            <Input
              value={newBookTitle}
              onChange={(event) => setNewBookTitle(event.target.value)}
              placeholder={t({
                zh: "新词库名称（可选）",
                en: "New book title (optional)",
              })}
              aria-label={t({ zh: "新词库名称", en: "New book title" })}
              className="h-11 max-w-56 text-base"
            />
          )}
        </div>

        {advancedQuery.isPending ? (
          <p
            role="status"
            className="flex items-center gap-2 text-sm text-muted-foreground"
          >
            <Loader2 className="size-4 animate-spin" />
            {t({ zh: "正在加载高级词…", en: "Loading advanced words…" })}
          </p>
        ) : words.length === 0 ? (
          <p role="status" className="text-sm text-muted-foreground">
            {t({
              zh: "当前筛选下没有高级备考词。",
              en: "No advanced words match the current filters.",
            })}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => toggleAll(true)}
              >
                {t({ zh: "全选", en: "Select all" })}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => toggleAll(false)}
              >
                {t({ zh: "清空", en: "Clear" })}
              </Button>
              <span className="text-xs text-muted-foreground">
                {t({
                  zh: `已选 ${selected.size}/${words.length} 词`,
                  en: `${selected.size}/${words.length} selected`,
                })}
              </span>
            </div>
            <div className="grid max-h-80 gap-1.5 overflow-y-auto rounded-xl border p-3 sm:grid-cols-2">
              {words.map((word) => (
                <label
                  key={word.id}
                  className={`flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors ${
                    selected.has(word.id)
                      ? "bg-secondary text-foreground"
                      : "text-muted-foreground hover:bg-secondary/50"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(word.id)}
                    onChange={(event) =>
                      toggleWord(word.id, event.target.checked)
                    }
                    className="size-4 accent-[var(--primary)]"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="font-semibold">{word.headword}</span>
                    <span className="ml-2 text-muted-foreground">
                      {word.meaning_zh}
                    </span>
                    <WordTagBadges
                      exam_tags={word.exam_tags}
                      cefr_band={word.cefr_band}
                    />
                  </span>
                </label>
              ))}
            </div>
          </>
        )}

        <div className="flex flex-wrap items-center gap-3 border-t pt-4">
          <Button disabled={!canTransfer} onClick={() => transfer.mutate()}>
            {transfer.isPending ? (
              <Loader2 className="animate-spin" />
            ) : (
              <Send />
            )}
            {t({
              zh: `转入教学词库（${selected.size} 词）`,
              en: `Transfer to teaching book (${selected.size} words)`,
            })}
          </Button>
          <p className="text-xs text-muted-foreground">
            {t({
              zh: "未通过审核或授权不齐的词条会被服务端拒绝；同库已收的词自动跳过。",
              en: "Words that are not approved or lack a license are rejected by the server; duplicates already in the book are skipped.",
            })}
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
