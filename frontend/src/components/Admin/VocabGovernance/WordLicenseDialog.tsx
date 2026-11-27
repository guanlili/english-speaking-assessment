import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import {
  ApiError,
  type VocabularyLicenseUpdate,
  VocabularyService,
  type VocabularyWordLicenseItem,
  type VocabularyWordPublic,
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
  isDemoSource,
  isoToLocalInput,
  licenseStatusLabel,
  localInputToIso,
  sourceTypeLabel,
  VOCAB_SOURCE_TYPES,
} from "@/lib/vocabGovernance"

interface Draft {
  sourceType: string
  owner: string
  ref: string
  expiresAt: string
  docUrl: string
  note: string
}

function emptyDraft(): Draft {
  return {
    sourceType: "self_built",
    owner: "",
    ref: "",
    expiresAt: "",
    docUrl: "",
    note: "",
  }
}

function draftFromItem(item: VocabularyWordLicenseItem): Draft {
  return {
    sourceType: item.source_type || "self_built",
    owner: item.license_owner ?? "",
    ref: item.license_ref ?? "",
    expiresAt: isoToLocalInput(item.license_expires_at),
    docUrl: item.authorization_doc_url ?? "",
    note: item.license_note ?? "",
  }
}

/**
 * 词条级授权编辑弹窗（管理员词库详情词条行入口）。
 * 字段口径与词库级一致；保存后失效词库详情与授权台账查询。
 */
export function WordLicenseDialog({
  word,
  initial,
  isAdmin,
  onClose,
  onSaved,
}: {
  word: VocabularyWordPublic | null
  initial: VocabularyWordLicenseItem | null | undefined
  isAdmin: boolean
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [loadedId, setLoadedId] = useState<string | null>(null)

  if (word && word.id !== loadedId) {
    setLoadedId(word.id)
    setDraft(initial ? draftFromItem(initial) : emptyDraft())
  }
  if (!word && loadedId !== null) {
    setLoadedId(null)
    setDraft(emptyDraft())
  }

  const save = useMutation({
    mutationFn: () => {
      if (!word) throw new Error("missing word")
      const payload: VocabularyLicenseUpdate = {
        source_type: draft.sourceType,
        license_owner: draft.owner.trim() || null,
        license_ref: draft.ref.trim() || null,
        license_expires_at: localInputToIso(draft.expiresAt),
        authorization_doc_url: draft.docUrl.trim() || null,
        license_note: draft.note.trim() || null,
      }
      return VocabularyService.updateWordLicense({
        word_id: word.id,
        vocabularyLicenseUpdate: payload,
      })
    },
    onSuccess: () => {
      toast.success(t({ zh: "词条授权已保存。", en: "Word license saved." }))
      queryClient.invalidateQueries({ queryKey: ["admin", "vocab-books"] })
      queryClient.invalidateQueries({ queryKey: ["admin", "vocab-book"] })
      queryClient.invalidateQueries({
        queryKey: ["admin", "vocab-book-license"],
      })
      onSaved()
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
      if (error.status === 403) {
        toast.error(
          t({
            zh: "没有权限修改词条授权（仅学校管理员）。",
            en: "No permission to edit this word's license (school admins only).",
          }),
        )
        return
      }
      if (error.status === 404) {
        toast.error(
          t({ zh: "词条不存在或已被移除。", en: "Word not found or removed." }),
        )
        return
      }
      toast.error(
        t({ zh: "保存失败，请重试。", en: "Save failed — please retry." }),
      )
    },
  })

  const demo = initial ? isDemoSource(initial.source_type) : false

  return (
    <Dialog
      open={word !== null}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {word?.headword}
            {initial && (
              <Badge variant="secondary">
                {t(licenseStatusLabel(initial.license_status))}
              </Badge>
            )}
            {demo && (
              <Badge variant="destructive">
                {t({ zh: "演示 Mock", en: "Demo mock" })}
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "词条授权随词条留存；改动写入本校审计记录。",
              en: "The word's license travels with the entry; changes are written to the school audit log.",
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          {demo && (
            <div className="rounded-xl border border-amber-300/50 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-950/20 dark:text-amber-200">
              {t({
                zh: "演示 / Mock 内容：仅本地演示，不用于生产。",
                en: "Demo / mock content: local demonstration only — not for production.",
              })}
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="word-license-source">
              {t({ zh: "来源类型", en: "Source type" })}
            </Label>
            <select
              id="word-license-source"
              value={draft.sourceType}
              disabled={!isAdmin}
              onChange={(event) =>
                setDraft((prev) => ({
                  ...prev,
                  sourceType: event.target.value,
                }))
              }
              className="h-11 w-full rounded-xl border border-input bg-card px-3 text-base text-foreground"
            >
              {VOCAB_SOURCE_TYPES.map((value) => (
                <option key={value} value={value}>
                  {t(sourceTypeLabel(value))}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="word-license-owner">
                {t({ zh: "授权方", en: "License owner" })}
              </Label>
              <Input
                id="word-license-owner"
                value={draft.owner}
                disabled={!isAdmin}
                onChange={(event) =>
                  setDraft((prev) => ({ ...prev, owner: event.target.value }))
                }
                className="h-11 text-base"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="word-license-ref">
                {t({
                  zh: "凭证（文号 / 链接）",
                  en: "License ref (no. / URL)",
                })}
              </Label>
              <Input
                id="word-license-ref"
                value={draft.ref}
                disabled={!isAdmin}
                onChange={(event) =>
                  setDraft((prev) => ({ ...prev, ref: event.target.value }))
                }
                className="h-11 text-base"
              />
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="word-license-expires">
                {t({ zh: "到期日（可选）", en: "Expires at (optional)" })}
              </Label>
              <Input
                id="word-license-expires"
                type="datetime-local"
                value={draft.expiresAt}
                disabled={!isAdmin}
                onChange={(event) =>
                  setDraft((prev) => ({
                    ...prev,
                    expiresAt: event.target.value,
                  }))
                }
                className="h-11 text-base"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="word-license-doc">
                {t({ zh: "授权书链接（可选）", en: "Doc URL (optional)" })}
              </Label>
              <Input
                id="word-license-doc"
                value={draft.docUrl}
                disabled={!isAdmin}
                onChange={(event) =>
                  setDraft((prev) => ({ ...prev, docUrl: event.target.value }))
                }
                className="h-11 text-base"
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="word-license-note">
              {t({ zh: "备注（可选）", en: "Note (optional)" })}
            </Label>
            <Textarea
              id="word-license-note"
              value={draft.note}
              disabled={!isAdmin}
              onChange={(event) =>
                setDraft((prev) => ({ ...prev, note: event.target.value }))
              }
              className="min-h-16 text-base"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t({ zh: "取消", en: "Cancel" })}
          </Button>
          {isAdmin && (
            <Button disabled={save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              {t({ zh: "保存", en: "Save" })}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
