import { useMutation } from "@tanstack/react-query"
import { Loader2, Plus, Trash2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import {
  ApiError,
  VocabularyService,
  type VocabularyWordPublic,
  type VocabularyWordUpdate,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useI18n } from "@/lib/i18n"
import {
  CEFR_BAND_LABELS,
  CEFR_BANDS,
  type CefrBand,
  EXAM_TAG_LABELS,
  VOCAB_EXAM_TAGS,
  type VocabExamTag,
} from "@/lib/terms"
import {
  CODE_DUPLICATE_WORD,
  CODE_VERSION_CONFLICT,
  MORPHOLOGY_KINDS,
  type MorphologyPart,
  parseDetailCode,
  REVIEW_STATUS_LABELS,
  serializeMorphology,
  validateMorphology,
} from "@/lib/vocabContentReview"

/** 可接受拼写变体的分隔符：逗号 / 斜杠 / 空白逗号都兼容。 */
const SPELLING_SPLIT_RE = /[,/、\s]+/

interface DraftState {
  partOfSpeech: string
  meaningZh: string
  meaningEn: string
  exampleEn: string
  audioUrl: string
  spellings: string
  morphology: MorphologyPart[]
  examTags: string[]
  cefrBand: string
}

function emptyDraft(): DraftState {
  return {
    partOfSpeech: "",
    meaningZh: "",
    meaningEn: "",
    exampleEn: "",
    audioUrl: "",
    spellings: "",
    morphology: [],
    examTags: [],
    cefrBand: "",
  }
}

function draftFromWord(word: VocabularyWordPublic): DraftState {
  return {
    partOfSpeech: word.part_of_speech ?? "",
    meaningZh: word.meaning_zh ?? "",
    meaningEn: word.meaning_en ?? "",
    exampleEn: word.example_en ?? "",
    audioUrl: word.audio_url ?? "",
    spellings: (word.accepted_spellings ?? []).join(", "),
    morphology: (word.morphology ?? []).map((part) => ({
      text: part.text ?? "",
      gloss: part.gloss ?? "",
      kind: part.kind ?? "",
    })),
    examTags: [...(word.exam_tags ?? [])],
    cefrBand: word.cefr_band ?? "",
  }
}

/**
 * 词条编辑弹窗（管理员词库详情 / 审核面板共用）。
 *
 * - 提交带 `expected_version=word.version` 乐观锁；
 * - 409 版本冲突 / 同库重复键给双语明确提示并提示刷新，不静默更新；
 * - 词法走结构化行编辑，校验不过阻断保存，不静默丢失。
 */
export function WordEditDialog({
  word,
  onClose,
  onSaved,
}: {
  word: VocabularyWordPublic | null
  onClose: () => void
  onSaved: (updated: VocabularyWordPublic) => void
}) {
  const { t, lang } = useI18n()
  const [draft, setDraft] = useState<DraftState>(emptyDraft)
  const [loadedId, setLoadedId] = useState<string | null>(null)

  if (word && word.id !== loadedId) {
    setLoadedId(word.id)
    setDraft(draftFromWord(word))
  }
  if (!word && loadedId !== null) {
    setLoadedId(null)
    setDraft(emptyDraft())
  }

  const setPatch = (patch: Partial<DraftState>) =>
    setDraft((prev) => ({ ...prev, ...patch }))

  const updateRow = (index: number, patch: Partial<MorphologyPart>) =>
    setDraft((prev) => ({
      ...prev,
      morphology: prev.morphology.map((row, i) =>
        i === index ? { ...row, ...patch } : row,
      ),
    }))

  const toggleExamTag = (tag: string) =>
    setDraft((prev) => ({
      ...prev,
      examTags: prev.examTags.includes(tag)
        ? prev.examTags.filter((item) => item !== tag)
        : [...prev.examTags, tag],
    }))

  const save = useMutation({
    mutationFn: () => {
      if (!word) throw new Error("missing word")
      const spellings = draft.spellings
        .split(SPELLING_SPLIT_RE)
        .map((item) => item.trim())
        .filter((item) => item.length > 0)
      const payload: VocabularyWordUpdate = {
        part_of_speech: draft.partOfSpeech.trim() || null,
        meaning_zh: draft.meaningZh.trim(),
        meaning_en: draft.meaningEn.trim() || null,
        accepted_spellings: spellings.length > 0 ? spellings : null,
        example_en: draft.exampleEn.trim() || null,
        audio_url: draft.audioUrl.trim() || null,
        morphology: serializeMorphology(draft.morphology),
        exam_tags: draft.examTags.length > 0 ? draft.examTags : null,
        cefr_band: draft.cefrBand || null,
        expected_version: word.version ?? null,
      }
      return VocabularyService.updateWord({
        word_id: word.id,
        vocabularyWordUpdate: payload,
      })
    },
    onSuccess: (updated) => {
      toast.success(t({ zh: "词条已保存。", en: "Word entry saved." }))
      onSaved(updated)
    },
    onError: (error) => {
      if (!(error instanceof ApiError)) {
        toast.error(
          t({
            zh: "保存失败，请检查网络后重试。",
            en: "Save failed — check your connection and retry.",
          }),
        )
        return
      }
      const detail =
        typeof error.body === "object" && error.body !== null
          ? ((error.body as { detail?: unknown }).detail ?? error.message)
          : error.message
      if (error.status === 409) {
        if (parseDetailCode(detail, CODE_DUPLICATE_WORD) !== null) {
          const headword = parseDetailCode(detail, CODE_DUPLICATE_WORD)
          toast.error(
            t({
              zh: `与词库内已有词条「${headword ?? ""}」重复：请修改释义或换词后再保存。`,
              en: `Duplicate of "${headword ?? ""}" in this book — change the meaning or the word.`,
            }),
          )
          return
        }
        toast.error(
          parseDetailCode(detail, CODE_VERSION_CONFLICT) !== null ||
            detail === CODE_VERSION_CONFLICT
            ? t({
                zh: "词条已被他人修改：版本不一致，请刷新页面后重新编辑。",
                en: "This word changed since you opened it — refresh and edit again.",
              })
            : t({
                zh: "词条状态冲突，请刷新后重试。",
                en: "Word state conflict — refresh and retry.",
              }),
        )
        return
      }
      if (error.status === 403) {
        toast.error(
          t({
            zh: "没有权限编辑这个词条。",
            en: "No permission to edit this word.",
          }),
        )
        return
      }
      toast.error(
        t({
          zh: "保存失败，请重试。",
          en: "Save failed — please retry.",
        }),
      )
    },
  })

  const resolveLocal = (bi: { zh: string; en: string }) =>
    lang === "en" ? bi.en : bi.zh

  const morphError = validateMorphology(draft.morphology)

  const statusLabel = word
    ? (REVIEW_STATUS_LABELS[word.review_status ?? "pending"] ??
      REVIEW_STATUS_LABELS.pending)
    : null

  const canSubmit =
    draft.meaningZh.trim().length > 0 && morphError === null && !save.isPending

  return (
    <Dialog
      open={word !== null}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {word?.headword}
            {statusLabel && <Badge variant="secondary">{t(statusLabel)}</Badge>}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "保存后词条版本号递增；已通过的词条被改内容会回到待审。",
              en: "Saving bumps the version; an approved word that changes returns to pending.",
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="word-edit-meaning-zh">
                {t({
                  zh: "中文释义（必填）",
                  en: "Chinese meaning (required)",
                })}
              </Label>
              <Input
                id="word-edit-meaning-zh"
                value={draft.meaningZh}
                onChange={(event) =>
                  setPatch({ meaningZh: event.target.value })
                }
                className="h-11 text-base"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="word-edit-pos">
                {t({ zh: "词性", en: "Part of speech" })}
              </Label>
              <Input
                id="word-edit-pos"
                value={draft.partOfSpeech}
                onChange={(event) =>
                  setPatch({ partOfSpeech: event.target.value })
                }
                placeholder="n. / v. / adj. …"
                className="h-11 text-base"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="word-edit-meaning-en">
              {t({ zh: "英文释义（可选）", en: "English meaning (optional)" })}
            </Label>
            <Input
              id="word-edit-meaning-en"
              value={draft.meaningEn}
              onChange={(event) => setPatch({ meaningEn: event.target.value })}
              className="h-11 text-base"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="word-edit-example">
              {t({ zh: "例句（可选）", en: "Example sentence (optional)" })}
            </Label>
            <Textarea
              id="word-edit-example"
              value={draft.exampleEn}
              onChange={(event) => setPatch({ exampleEn: event.target.value })}
              className="min-h-16 text-base"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="word-edit-audio">
                {t({ zh: "音频 URL（可选）", en: "Audio URL (optional)" })}
              </Label>
              <Input
                id="word-edit-audio"
                value={draft.audioUrl}
                onChange={(event) => setPatch({ audioUrl: event.target.value })}
                className="h-11 text-base"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="word-edit-spellings">
                {t({
                  zh: "可接受拼写（逗号分隔，可选）",
                  en: "Accepted spellings (comma-separated, optional)",
                })}
              </Label>
              <Input
                id="word-edit-spellings"
                value={draft.spellings}
                onChange={(event) =>
                  setPatch({ spellings: event.target.value })
                }
                className="h-11 text-base"
              />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>
                {t({
                  zh: "考试标签（可多选，可选）",
                  en: "Exam tags (multi-select, optional)",
                })}
              </Label>
              <div className="flex flex-wrap gap-2">
                {VOCAB_EXAM_TAGS.map((tag: VocabExamTag) => {
                  const checked = draft.examTags.includes(tag)
                  return (
                    <label
                      key={tag}
                      className={`flex h-11 cursor-pointer items-center gap-2 rounded-xl border px-3 text-base transition-colors ${
                        checked
                          ? "border-primary bg-primary/10 text-foreground"
                          : "border-input bg-card text-muted-foreground"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleExamTag(tag)}
                        className="h-4 w-4"
                      />
                      {t(EXAM_TAG_LABELS[tag])}
                    </label>
                  )
                })}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="word-edit-cefr">
                {t({ zh: "CEFR 档位（可选）", en: "CEFR band (optional)" })}
              </Label>
              <select
                id="word-edit-cefr"
                value={draft.cefrBand}
                onChange={(event) => setPatch({ cefrBand: event.target.value })}
                className="h-11 w-full rounded-xl border border-input bg-card px-3 text-base text-foreground"
              >
                <option value="">
                  {t({ zh: "未标注", en: "Not marked" })}
                </option>
                {CEFR_BANDS.map((band: CefrBand) => (
                  <option key={band} value={band}>
                    {t(CEFR_BAND_LABELS[band])}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">
                {t({
                  zh: "档位是词条内容标签，不代表对学生的能力评定。",
                  en: "The band is a content label for the word, not a proficiency rating for students.",
                })}
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>
                {t({ zh: "词法拆解（可选）", en: "Word parts (optional)" })}
              </Label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setPatch({
                    morphology: [
                      ...draft.morphology,
                      { text: "", gloss: "", kind: "root" },
                    ],
                  })
                }
              >
                <Plus />
                {t({ zh: "加一行", en: "Add part" })}
              </Button>
            </div>
            {draft.morphology.length === 0 && (
              <p className="text-xs text-muted-foreground">
                {t({
                  zh: "词根拼装题需要词条带词法拆解；没有可留空。",
                  en: "Word Parts questions need morphology; leave empty if none.",
                })}
              </p>
            )}
            <ul className="space-y-2">
              {draft.morphology.map((row, index) => (
                <li
                  key={`morph-${index}`}
                  className="grid grid-cols-[1fr_1fr_auto] items-center gap-2 sm:grid-cols-[1fr_1fr_110px_auto]"
                >
                  <Input
                    value={row.text}
                    aria-label={t({ zh: "片段", en: "Part text" })}
                    placeholder="teach"
                    onChange={(event) =>
                      updateRow(index, { text: event.target.value })
                    }
                    className="h-11 text-base"
                  />
                  <Input
                    value={row.gloss}
                    aria-label={t({ zh: "释义", en: "Gloss" })}
                    placeholder="教"
                    onChange={(event) =>
                      updateRow(index, { gloss: event.target.value })
                    }
                    className="h-11 text-base"
                  />
                  <select
                    value={row.kind}
                    aria-label={t({ zh: "类型", en: "Kind" })}
                    onChange={(event) =>
                      updateRow(index, { kind: event.target.value })
                    }
                    className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
                  >
                    {MORPHOLOGY_KINDS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {t(option.label)}
                      </option>
                    ))}
                  </select>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={t({ zh: "删除该行", en: "Remove row" })}
                    onClick={() =>
                      setPatch({
                        morphology: draft.morphology.filter(
                          (_, i) => i !== index,
                        ),
                      })
                    }
                  >
                    <Trash2 />
                  </Button>
                </li>
              ))}
            </ul>
            {morphError && (
              <p role="alert" className="text-sm text-destructive">
                {resolveLocal(morphError)}
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t({ zh: "取消", en: "Cancel" })}
          </Button>
          <Button disabled={!canSubmit} onClick={() => save.mutate()}>
            {save.isPending ? <Loader2 className="animate-spin" /> : null}
            {t({ zh: "保存", en: "Save" })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
