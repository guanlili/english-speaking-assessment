import { useMutation } from "@tanstack/react-query"
import {
  ChevronDown,
  ChevronRight,
  Pencil,
  Scissors,
  Trash2,
  Undo2,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { PassageWithSentences } from "@/client"
import { AdminService } from "@/client"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import AudioSetter from "@/components/Practice/AudioSetter"
import { CopyContentButton } from "@/components/Teaching/CopyContentButton"
import ExamItemSettingsButton from "@/components/Teaching/ExamItemSettingsButton"
import { PassageSentences } from "@/components/Teaching/PassageSentences"
import { ReadingSentences } from "@/components/Teaching/ReadingSentences"
import { ReadOnlyContentBadge } from "@/components/Teaching/ReadOnlyContentBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useCanEditContent } from "@/hooks/useCanEditContent"
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"
export function PassageCard({
  passage,
  unitTitle,
  expanded,
  onToggle,
  onEdit,
  onDelete,
  onMutated,
}: {
  passage: PassageWithSentences
  unitTitle: string
  expanded: boolean
  onToggle: () => void
  onEdit: (passage: PassageWithSentences) => void
  onDelete: () => void
  onMutated: () => void
}) {
  const { t } = useI18n()
  const editable = useCanEditContent()(passage.owner_id)
  const [splitConfirm, setSplitConfirm] = useState(false)
  const [unsplitConfirm, setUnsplitConfirm] = useState(false)
  const splitPassage = useMutation({
    mutationFn: () =>
      AdminService.splitPassageIntoReadings({ passage_id: passage.id }),
    onSuccess: (data) => {
      toast.success(
        t({
          zh: `已拆分出 ${data.created} 句：组卷时这篇文章将按句出题`,
          en: `Split into ${data.created} sentences — this article now becomes one question per sentence when composing practice`,
        }),
      )
      setSplitConfirm(false)
      if (!expanded) onToggle()
      onMutated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(
        err.body?.detail === "正文只有一个段落，无需拆分；请先用换行分段" ||
          err.body?.detail === "正文不足两句，无法按句拆分"
          ? t({
              zh: "正文至少需要两句才能拆分。",
              en: "The text needs at least two sentences to split.",
            })
          : extractErrorMessage(err),
      ),
  })
  const unsplitPassage = useMutation({
    mutationFn: () =>
      AdminService.unsplitPassageReadings({ passage_id: passage.id }),
    onSuccess: () => {
      toast.success(
        t({
          zh: "已取消拆分：此后组卷回到整篇一道题",
          en: "Split removed — future practices use the whole article as one question",
        }),
      )
      setUnsplitConfirm(false)
      onMutated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(extractErrorMessage(err)),
  })
  return (
    <Card data-testid={`passage-${passage.id}`}>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3 space-y-0">
        <div className="min-w-0 flex-1">
          <CardTitle className="text-base leading-relaxed">
            <button
              type="button"
              className="flex min-h-11 w-full items-center gap-2 text-left"
              aria-expanded={expanded}
              aria-controls={`passage-content-${passage.id}`}
              onClick={onToggle}
            >
              {expanded ? (
                <ChevronDown className="size-4 shrink-0" />
              ) : (
                <ChevronRight className="size-4 shrink-0" />
              )}
              <span className="min-w-0 break-words [overflow-wrap:anywhere]">
                {passage.title}
              </span>
            </button>
          </CardTitle>
          <CardDescription className="mt-1 flex flex-wrap items-center gap-2">
            <Badge variant="outline">{unitTitle}</Badge>
            <span>
              {(passage.reading_segments ?? []).length > 0
                ? t({
                    zh: `按句出题 · ${(passage.reading_segments ?? []).length} 句`,
                    en: `${(passage.reading_segments ?? []).length} sentence questions`,
                  })
                : t({ zh: "1 道文章朗读题", en: "1 read-aloud question" })}
            </span>
            {(passage.reading_segments ?? []).length > 0 && (
              <span>
                {t({
                  zh: `${(passage.reading_segments ?? []).length} 句朗读分句`,
                  en: `${(passage.reading_segments ?? []).length} reading sentences`,
                })}
              </span>
            )}
            <span>
              {t({
                zh: `${(passage.sentences ?? []).length} 句复述`,
                en: `${(passage.sentences ?? []).length} repeat sentences`,
              })}
            </span>
            {passage.is_active === false && (
              <Badge variant="secondary">
                {t({ zh: "已停用", en: "Disabled" })}
              </Badge>
            )}
            {!editable && <ReadOnlyContentBadge />}
          </CardDescription>
        </div>
        <div className="flex max-w-full flex-wrap items-center gap-1.5">
          <CopyContentButton
            source={
              passage.copied_from_id
                ? { kind: "passage", id: passage.copied_from_id }
                : undefined
            }
            label={t({
              zh: `复制篇目 ${passage.title}`,
              en: `Copy passage ${passage.title}`,
            })}
            copy={() => AdminService.copyPassage({ passage_id: passage.id })}
            onCopied={onEdit}
          />
          <Button
            variant="outline"
            size="sm"
            className="min-h-11"
            aria-expanded={expanded}
            onClick={onToggle}
          >
            {expanded
              ? t({ zh: "收起", en: "Collapse" })
              : t({ zh: "查看文章", en: "View Text" })}
          </Button>
          {editable && !passage.reading_split && (
            <Button
              variant="outline"
              size="sm"
              className="min-h-11"
              disabled={splitPassage.isPending}
              title={t({
                zh: "按原文顺序拆句，组卷时这篇文章按句出题",
                en: "Split sentences in source order; the article then becomes one question per sentence",
              })}
              onClick={() => setSplitConfirm(true)}
            >
              <Scissors />
              {t({ zh: "自动拆分句子", en: "Auto-split Sentences" })}
            </Button>
          )}
          {editable && passage.reading_split && (
            <Button
              variant="outline"
              size="sm"
              className="min-h-11"
              disabled={unsplitPassage.isPending}
              title={t({
                zh: "取消拆分：此后组卷回到整篇一道题",
                en: "Remove the split — future practices use the whole article as one question",
              })}
              onClick={() => setUnsplitConfirm(true)}
            >
              <Undo2 />
              {t({ zh: "取消拆分", en: "Unsplit" })}
            </Button>
          )}
          {editable && (
            <Button
              variant="ghost"
              size="icon"
              aria-label={t({
                zh: `编辑 ${passage.title}`,
                en: `Edit ${passage.title}`,
              })}
              onClick={(e) => {
                e.stopPropagation()
                onEdit(passage)
              }}
            >
              <Pencil />
            </Button>
          )}
          <ExamItemSettingsButton
            itemType="passage"
            itemId={passage.id}
            text={passage.text ?? ""}
          />
          {editable && (
            <AudioSetter
              audioUrl={passage.audio_url}
              text={passage.text ?? ""}
              stopPropagation
              onSet={async (audio_url) => {
                await AdminService.updatePassage({
                  passage_id: passage.id,
                  passageUpdate: {
                    title: passage.title ?? "",
                    topic: passage.topic ?? "",
                    cefr_band: passage.cefr_band ?? "B1",
                    text: passage.text ?? "",
                    translation: passage.translation ?? undefined,
                    audio_url,
                    suggested_seconds: passage.suggested_seconds ?? 45,
                    is_active: passage.is_active ?? true,
                    unit_id: passage.unit_id ?? undefined,
                  },
                })
                onMutated()
              }}
            />
          )}
          {editable && (
            <Button
              variant="ghost"
              size="icon"
              aria-label={t({
                zh: `删除 ${passage.title}`,
                en: `Delete ${passage.title}`,
              })}
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
            >
              <Trash2 className="text-destructive" />
            </Button>
          )}
        </div>
      </CardHeader>
      {expanded && (
        <CardContent id={`passage-content-${passage.id}`} className="space-y-4">
          <p className="whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-sm [overflow-wrap:anywhere]">
            {passage.text}
          </p>
          <ReadingSentences
            segments={passage.reading_segments ?? []}
            seconds={passage.reading_sentence_seconds}
            audio={passage.reading_sentence_audio}
            passageId={passage.id}
            onMutated={onMutated}
            readOnly={!editable}
          />
          <PassageSentences
            passage={passage}
            onMutated={onMutated}
            readOnly={!editable}
          />
        </CardContent>
      )}

      <ConfirmDialog
        open={splitConfirm}
        title={t({
          zh: `拆分「${passage.title}」的朗读句子？`,
          en: `Split reading sentences for "${passage.title}"?`,
        })}
        description={t({
          zh: "按原文顺序拆分全部句子，折叠在文章下。组卷时这篇文章按句出题，学生逐句朗读；修改正文后分句自动更新，听句复述单独管理。",
          en: "All sentences appear in source order under the collapsible article. Composing practice then creates one question per sentence — students read aloud sentence by sentence. Sentence views update with the text; Listen & Repeat items are managed separately.",
        })}
        confirmText={t({ zh: "拆分", en: "Split" })}
        onOpenChange={(next) => {
          if (!next) setSplitConfirm(false)
        }}
        onConfirm={async () => {
          await splitPassage.mutateAsync()
        }}
      />
      <ConfirmDialog
        open={unsplitConfirm}
        title={t({
          zh: `取消拆分「${passage.title}」？`,
          en: `Remove the split for "${passage.title}"?`,
        })}
        description={t({
          zh: "此后组卷回到整篇一道题。已发布练习的快照不受影响，学生继续按发布时的逐句题单作答。",
          en: "Future practices go back to the whole article as one question. Already-published exercises keep their snapshots — students finish them as published.",
        })}
        confirmText={t({ zh: "取消拆分", en: "Unsplit" })}
        onOpenChange={(next) => {
          if (!next) setUnsplitConfirm(false)
        }}
        onConfirm={async () => {
          await unsplitPassage.mutateAsync()
        }}
      />
    </Card>
  )
}
