import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Download, Loader2, ShieldCheck } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import {
  ApiError,
  type VocabularyBookLicenseDetail,
  type VocabularyLicenseUpdate,
  VocabularyService,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { localDateStamp } from "@/lib/dates"
import { useI18n } from "@/lib/i18n"
import { formatDateTime } from "@/lib/time"
import {
  describeQueryError,
  formatAuditChanges,
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

function draftFromLicense(
  license: VocabularyBookLicenseDetail["license"],
): Draft {
  return {
    sourceType: license.source_type || "self_built",
    owner: license.license_owner ?? "",
    ref: license.license_ref ?? "",
    expiresAt: isoToLocalInput(license.license_expires_at),
    docUrl: license.authorization_doc_url ?? "",
    note: license.license_note ?? "",
  }
}

/**
 * 词库级授权台账：可编辑授权字段、查看本校审计记录、导出授权清单 CSV。
 * 写操作仅学校管理员；教师 / 运营只读（后端 403 兜底）。
 */
export function BookLicensePanel({
  bookId,
  license,
  isAdmin,
}: {
  bookId: string
  license: VocabularyBookLicenseDetail | undefined
  isAdmin: boolean
}) {
  const { t, lang } = useI18n()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [loadedKey, setLoadedKey] = useState<string | null>(null)

  const licenseKey = license
    ? `${license.book_id}:${license.license.source_type}`
    : null
  if (license && licenseKey !== loadedKey) {
    setLoadedKey(licenseKey)
    setDraft(draftFromLicense(license.license))
  }
  if (!license && loadedKey !== null) {
    setLoadedKey(null)
    setDraft(emptyDraft())
  }

  const invalidateLicense = () => {
    queryClient.invalidateQueries({ queryKey: ["admin", "vocab-books"] })
    queryClient.invalidateQueries({ queryKey: ["admin", "vocab-book"] })
    queryClient.invalidateQueries({
      queryKey: ["admin", "vocab-book-license", bookId],
    })
    queryClient.invalidateQueries({
      queryKey: ["admin", "vocab-license-alerts"],
    })
  }

  const save = useMutation({
    mutationFn: () => {
      const payload: VocabularyLicenseUpdate = {
        source_type: draft.sourceType,
        license_owner: draft.owner.trim() || null,
        license_ref: draft.ref.trim() || null,
        license_expires_at: localInputToIso(draft.expiresAt),
        authorization_doc_url: draft.docUrl.trim() || null,
        license_note: draft.note.trim() || null,
      }
      return VocabularyService.updateBookLicense({
        book_id: bookId,
        vocabularyLicenseUpdate: payload,
      })
    },
    onSuccess: () => {
      toast.success(t({ zh: "授权信息已保存。", en: "License info saved." }))
      invalidateLicense()
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
            zh: "没有权限修改授权（仅学校管理员）。",
            en: "No permission to edit the license (school admins only).",
          }),
        )
        return
      }
      if (error.status === 404) {
        toast.error(
          t({ zh: "词库不存在或已被移除。", en: "Book not found or removed." }),
        )
        return
      }
      toast.error(
        t({ zh: "保存失败，请重试。", en: "Save failed — please retry." }),
      )
    },
  })

  const exportCsv = useMutation({
    mutationFn: async () => {
      const csv = await VocabularyService.exportLicenseCsv()
      const blob = new Blob([String(csv)], {
        type: "text/csv;charset=utf-8",
      })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = `vocabulary-license-${localDateStamp()}.csv`
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    },
    onSuccess: () => {
      toast.success(t({ zh: "授权清单已导出。", en: "License list exported." }))
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 403) {
        toast.error(
          t({
            zh: "没有权限导出授权清单（仅学校管理员）。",
            en: "No permission to export the license list (school admins only).",
          }),
        )
        return
      }
      toast.error(
        t({ zh: "导出失败，请重试。", en: "Export failed — please retry." }),
      )
    },
  })

  const auditQuery = useQuery({
    queryKey: ["admin", "vocab-license-audit", bookId],
    queryFn: () =>
      VocabularyService.listLicenseAudit({ book_id: bookId, limit: 50 }),
  })

  const demo = license ? isDemoSource(license.license.source_type) : false

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="flex flex-wrap items-center gap-2 text-base">
            <ShieldCheck className="size-4 text-primary" />
            {t({ zh: "授权信息", en: "License" })}
            {license && (
              <Badge variant="secondary">
                {t(licenseStatusLabel(license.license.license_status))}
              </Badge>
            )}
            {demo && (
              <Badge variant="destructive">
                {t({ zh: "演示 Mock", en: "Demo mock" })}
              </Badge>
            )}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "教材 / 授权引进来源发布前须填授权方与凭证；改动会逐字段留痕。",
              en: "Textbook / licensed sources need an owner and ref before publishing; every change is audited field by field.",
            })}
          </CardDescription>
        </div>
        {isAdmin && (
          <Button
            variant="outline"
            size="sm"
            disabled={exportCsv.isPending}
            onClick={() => exportCsv.mutate()}
          >
            {exportCsv.isPending ? (
              <Loader2 className="animate-spin" />
            ) : (
              <Download />
            )}
            {t({ zh: "导出授权清单", en: "Export license list" })}
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-5">
        {demo && (
          <div className="rounded-xl border border-amber-300/50 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-950/20 dark:text-amber-200">
            {t({
              zh: "演示 / Mock 内容：仅本地演示，不用于生产。",
              en: "Demo / mock content: local demonstration only — not for production.",
            })}
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="book-license-source">
              {t({ zh: "来源类型", en: "Source type" })}
            </Label>
            <select
              id="book-license-source"
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
          <div className="space-y-1.5">
            <Label htmlFor="book-license-owner">
              {t({ zh: "授权方", en: "License owner" })}
            </Label>
            <Input
              id="book-license-owner"
              value={draft.owner}
              disabled={!isAdmin}
              onChange={(event) =>
                setDraft((prev) => ({ ...prev, owner: event.target.value }))
              }
              placeholder={t({
                zh: "如：出版社 / 版权方名称",
                en: "e.g. publisher / rights holder",
              })}
              className="h-11 text-base"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="book-license-ref">
              {t({ zh: "凭证（文号 / 链接）", en: "License ref (no. / URL)" })}
            </Label>
            <Input
              id="book-license-ref"
              value={draft.ref}
              disabled={!isAdmin}
              onChange={(event) =>
                setDraft((prev) => ({ ...prev, ref: event.target.value }))
              }
              placeholder={t({
                zh: "授权文号或合同编号",
                en: "License no. or contract ID",
              })}
              className="h-11 text-base"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="book-license-expires">
              {t({ zh: "到期日（可选）", en: "Expires at (optional)" })}
            </Label>
            <Input
              id="book-license-expires"
              type="datetime-local"
              value={draft.expiresAt}
              disabled={!isAdmin}
              onChange={(event) =>
                setDraft((prev) => ({ ...prev, expiresAt: event.target.value }))
              }
              className="h-11 text-base"
            />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="book-license-doc">
              {t({
                zh: "授权书链接（可选）",
                en: "Authorization doc URL (optional)",
              })}
            </Label>
            <Input
              id="book-license-doc"
              value={draft.docUrl}
              disabled={!isAdmin}
              onChange={(event) =>
                setDraft((prev) => ({ ...prev, docUrl: event.target.value }))
              }
              placeholder="https://…"
              className="h-11 text-base"
            />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="book-license-note">
              {t({ zh: "备注（可选）", en: "Note (optional)" })}
            </Label>
            <Textarea
              id="book-license-note"
              value={draft.note}
              disabled={!isAdmin}
              onChange={(event) =>
                setDraft((prev) => ({ ...prev, note: event.target.value }))
              }
              className="min-h-16 text-base"
            />
          </div>
        </div>

        {isAdmin && (
          <div className="flex flex-wrap items-center gap-3">
            <Button disabled={save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              {t({ zh: "保存授权", en: "Save license" })}
            </Button>
            <p className="text-xs text-muted-foreground">
              {t({
                zh: "清空字段即清除对应授权信息；保存后审计记录自动更新。",
                en: "Clearing a field removes that info; the audit log updates after saving.",
              })}
            </p>
          </div>
        )}

        <div className="border-t pt-4">
          <p className="mb-2 text-sm font-medium">
            {t({ zh: "授权变更记录", en: "Change history" })}
          </p>
          {auditQuery.isPending ? (
            <Skeleton className="h-16 rounded-xl" />
          ) : auditQuery.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {t(
                describeQueryError(
                  auditQuery.error instanceof ApiError
                    ? auditQuery.error.status
                    : undefined,
                ),
              )}
            </p>
          ) : (auditQuery.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t({
                zh: "暂无授权变更记录。",
                en: "No license changes recorded yet.",
              })}
            </p>
          ) : (
            <ul className="space-y-2">
              {(auditQuery.data ?? []).map((row) => {
                const changes = formatAuditChanges(row.changes)
                return (
                  <li
                    key={row.id}
                    className="rounded-xl border border-border/70 bg-secondary/30 p-3 text-sm"
                  >
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">
                        {row.actor_name ?? row.actor_role ?? "–"}
                      </span>
                      <span>{formatDateTime(row.created_at ?? "", lang)}</span>
                      <span>
                        {row.target_type === "word"
                          ? t({ zh: "词条", en: "Word" })
                          : t({ zh: "词库", en: "Book" })}
                      </span>
                    </div>
                    {changes.length > 0 && (
                      <ul className="mt-1 space-y-0.5">
                        {changes.map((change) => (
                          <li key={change.field} className="text-xs">
                            <span className="text-muted-foreground">
                              {t(change.label)}：
                            </span>
                            <span className="text-destructive line-through">
                              {change.from ?? "（空）"}
                            </span>
                            {" → "}
                            <span className="text-primary">
                              {change.to ?? "（空）"}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                    {row.note && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {row.note}
                      </p>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
