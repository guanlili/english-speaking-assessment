import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { GitCompareArrows, History, Loader2, RotateCcw } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import {
  ApiError,
  type VocabularyBookVersionEntry,
  VocabularyService,
  type VocabularyVersionCompare,
  type VocabularyVersionDiffEntry,
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useI18n } from "@/lib/i18n"
import { formatDateTime } from "@/lib/time"
import {
  describeQueryError,
  diffDimensionLabel,
  formatSnapshotField,
  shortHash,
  versionActionLabel,
} from "@/lib/vocabGovernance"

/** 对比条目内容取值方向：新增取 to，删除取 from。 */
function entryValue(
  entry: VocabularyVersionDiffEntry,
  side: "from" | "to",
): Record<string, unknown> | null {
  const snapshot = side === "from" ? entry.from_entry : entry.to_entry
  return snapshot ?? null
}

export function VersionHistoryPanel({
  bookId,
  isAdmin,
}: {
  bookId: string
  isAdmin: boolean
}) {
  const { t, lang } = useI18n()
  const queryClient = useQueryClient()
  const [fromVersion, setFromVersion] = useState("")
  const [toVersion, setToVersion] = useState("")
  const [rollbackTarget, setRollbackTarget] =
    useState<VocabularyBookVersionEntry | null>(null)

  const versionsQuery = useQuery({
    queryKey: ["admin", "vocab-book-versions", bookId],
    queryFn: () => VocabularyService.listBookVersions({ book_id: bookId }),
  })

  const versions = versionsQuery.data?.items ?? []
  const fromNo = Number(fromVersion)
  const toNo = Number(toVersion)
  const compareEnabled =
    Number.isFinite(fromNo) &&
    Number.isFinite(toNo) &&
    fromNo > 0 &&
    toNo > 0 &&
    fromNo !== toNo

  const compareQuery = useQuery({
    queryKey: ["admin", "vocab-book-compare", bookId, fromVersion, toVersion],
    queryFn: () =>
      VocabularyService.compareBookVersions({
        book_id: bookId,
        from_version: fromNo,
        to_version: toNo,
      }),
    enabled: compareEnabled,
  })

  const invalidateVersions = () => {
    queryClient.invalidateQueries({
      queryKey: ["admin", "vocab-book-versions", bookId],
    })
    queryClient.invalidateQueries({ queryKey: ["admin", "vocab-book"] })
    queryClient.invalidateQueries({
      queryKey: ["admin", "vocab-book-license", bookId],
    })
    queryClient.invalidateQueries({ queryKey: ["admin", "vocab-books"] })
  }

  const rollback = useMutation({
    mutationFn: (target: VocabularyBookVersionEntry) =>
      VocabularyService.rollbackBookVersion({
        book_id: bookId,
        version_no: target.version_no,
      }),
    onSuccess: (_entry, target) => {
      toast.success(
        t({
          zh: `已回滚到版本 v${target.version_no}，并生成新的版本记录。`,
          en: `Rolled back to v${target.version_no}; a new version record was created.`,
        }),
      )
      setRollbackTarget(null)
      invalidateVersions()
    },
    onError: (error) => {
      if (!(error instanceof ApiError)) {
        toast.error(
          t({
            zh: "回滚失败，请检查网络后重试。",
            en: "Rollback failed — check your connection and retry.",
          }),
        )
        return
      }
      if (error.status === 403) {
        toast.error(
          t({
            zh: "没有权限回滚（仅学校管理员）。",
            en: "No permission to roll back (school admins only).",
          }),
        )
        return
      }
      if (error.status === 404) {
        toast.error(
          t({
            zh: "目标版本不存在或已被移除。",
            en: "Target version not found or removed.",
          }),
        )
        return
      }
      toast.error(
        t({ zh: "回滚失败，请重试。", en: "Rollback failed — please retry." }),
      )
    },
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          <History className="size-4 text-primary" />
          {t({ zh: "版本历史", en: "Version history" })}
        </CardTitle>
        <CardDescription>
          {t({
            zh: "每次词条变更固化为一个版本；可对比任意两版，管理员可回滚到历史快照。",
            en: "Every content change is frozen as a version; compare any two, and admins can roll back to an earlier snapshot.",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* 版本列表 */}
        {versionsQuery.isPending ? (
          <Skeleton className="h-24 rounded-xl" />
        ) : versionsQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {t(
              describeQueryError(
                versionsQuery.error instanceof ApiError
                  ? versionsQuery.error.status
                  : undefined,
              ),
            )}
          </p>
        ) : versions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t({
              zh: "这个词库还没有版本记录。",
              en: "No version records for this book yet.",
            })}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t({ zh: "版本", en: "Version" })}</TableHead>
                <TableHead>{t({ zh: "操作", en: "Action" })}</TableHead>
                <TableHead>{t({ zh: "操作人", en: "Actor" })}</TableHead>
                <TableHead>{t({ zh: "时间", en: "Time" })}</TableHead>
                <TableHead>{t({ zh: "词数", en: "Words" })}</TableHead>
                <TableHead>{t({ zh: "摘要", en: "Summary" })}</TableHead>
                <TableHead>{t({ zh: "哈希", en: "Hash" })}</TableHead>
                {isAdmin && (
                  <TableHead>{t({ zh: "操作", en: "Actions" })}</TableHead>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {versions.map((entry) => (
                <TableRow key={entry.version_no}>
                  <TableCell className="font-semibold tabular-nums">
                    v{entry.version_no}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {t(versionActionLabel(entry.action))}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {entry.actor_name ?? entry.actor_role ?? "–"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {entry.created_at
                      ? formatDateTime(entry.created_at, lang)
                      : "–"}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {entry.word_count ?? 0}
                  </TableCell>
                  <TableCell className="max-w-40 truncate text-muted-foreground">
                    {entry.summary ?? "–"}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {shortHash(entry.content_hash)}
                  </TableCell>
                  {isAdmin && (
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={rollback.isPending}
                        onClick={() => setRollbackTarget(entry)}
                      >
                        <RotateCcw />
                        {t({ zh: "回滚", en: "Rollback" })}
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        {/* 版本对比 */}
        <div className="border-t pt-4">
          <p className="mb-2 flex items-center gap-2 text-sm font-medium">
            <GitCompareArrows className="size-4 text-primary" />
            {t({ zh: "版本对比", en: "Compare versions" })}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label={t({ zh: "基准版本", en: "From version" })}
              value={fromVersion}
              onChange={(event) => setFromVersion(event.target.value)}
              className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
            >
              <option value="">
                {t({ zh: "基准版本…", en: "From version…" })}
              </option>
              {versions.map((entry) => (
                <option key={entry.version_no} value={String(entry.version_no)}>
                  v{entry.version_no}
                </option>
              ))}
            </select>
            <span className="text-muted-foreground">→</span>
            <select
              aria-label={t({ zh: "目标版本", en: "To version" })}
              value={toVersion}
              onChange={(event) => setToVersion(event.target.value)}
              className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
            >
              <option value="">
                {t({ zh: "目标版本…", en: "To version…" })}
              </option>
              {versions.map((entry) => (
                <option key={entry.version_no} value={String(entry.version_no)}>
                  v{entry.version_no}
                </option>
              ))}
            </select>
          </div>

          {!compareEnabled && (
            <p className="mt-2 text-sm text-muted-foreground">
              {t({
                zh: "选择两个不同版本后查看词条差异。",
                en: "Pick two different versions to see the word-level diff.",
              })}
            </p>
          )}
          {compareEnabled && compareQuery.isPending && (
            <div role="status" className="mt-3">
              <Skeleton className="h-20 rounded-xl" />
            </div>
          )}
          {compareEnabled && compareQuery.isError && (
            <p role="alert" className="mt-3 text-sm text-destructive">
              {t(
                describeQueryError(
                  compareQuery.error instanceof ApiError
                    ? compareQuery.error.status
                    : undefined,
                ),
              )}
            </p>
          )}
          {compareEnabled && compareQuery.data && (
            <CompareResult data={compareQuery.data} t={t} />
          )}
        </div>
      </CardContent>

      {/* 回滚二次确认 */}
      <Dialog
        open={rollbackTarget !== null}
        onOpenChange={(next) => {
          if (!next) setRollbackTarget(null)
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {t({
                zh: `回滚到版本 v${rollbackTarget?.version_no ?? ""}`,
                en: `Roll back to v${rollbackTarget?.version_no ?? ""}`,
              })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "回滚会把词库内容还原为该版本快照，并生成一条新的 rollback 版本。",
                en: "Rolling back restores the book to that snapshot and creates a new rollback version.",
              })}
            </DialogDescription>
          </DialogHeader>
          <ul className="space-y-1.5 rounded-xl border border-border/70 bg-secondary/30 p-3 text-sm">
            <li>
              {t({
                zh: "生成新版本、不删除历史：原有版本记录全部保留。",
                en: "A new version is created; history is not deleted — all earlier records stay.",
              })}
            </li>
            <li>
              {t({
                zh: "已发布任务快照不受影响：学生仍按发布当时的快照练习与判分。",
                en: "Published task snapshots are unaffected: students keep practicing and scoring against the snapshots fixed at publish time.",
              })}
            </li>
          </ul>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRollbackTarget(null)}>
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
            <Button
              variant="destructive"
              disabled={rollback.isPending}
              onClick={() => rollbackTarget && rollback.mutate(rollbackTarget)}
            >
              {rollback.isPending ? <Loader2 className="animate-spin" /> : null}
              {t({ zh: "确认回滚", en: "Confirm rollback" })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

function CompareResult({
  data,
  t,
}: {
  data: VocabularyVersionCompare
  t: (bi: { zh: string; en: string }) => string
}) {
  const added = data.added ?? []
  const removed = data.removed ?? []
  const changed = data.changed ?? []

  if (added.length === 0 && removed.length === 0 && changed.length === 0) {
    return (
      <p className="mt-3 text-sm text-muted-foreground">
        {t({
          zh: "两个版本之间没有词条差异。",
          en: "No word-level diff between the two versions.",
        })}
      </p>
    )
  }

  return (
    <div className="mt-3 space-y-4">
      {added.length > 0 && (
        <DiffGroup
          title={t({
            zh: `新增 ${added.length} 词`,
            en: `Added ${added.length}`,
          })}
          variant="secondary"
          entries={added}
          side="to"
          t={t}
        />
      )}
      {removed.length > 0 && (
        <DiffGroup
          title={t({
            zh: `删除 ${removed.length} 词`,
            en: `Removed ${removed.length}`,
          })}
          variant="destructive"
          entries={removed}
          side="from"
          t={t}
        />
      )}
      {changed.length > 0 && (
        <DiffGroup
          title={t({
            zh: `变更 ${changed.length} 词`,
            en: `Changed ${changed.length}`,
          })}
          variant="outline"
          entries={changed}
          side="both"
          t={t}
        />
      )}
    </div>
  )
}

function DiffGroup({
  title,
  variant,
  entries,
  side,
  t,
}: {
  title: string
  variant: "secondary" | "destructive" | "outline"
  entries: VocabularyVersionDiffEntry[]
  side: "from" | "to" | "both"
  t: (bi: { zh: string; en: string }) => string
}) {
  return (
    <div>
      <p className="mb-1.5">
        <Badge variant={variant}>{title}</Badge>
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t({ zh: "单词", en: "Word" })}</TableHead>
            {side === "both" ? (
              <>
                <TableHead>{t({ zh: "维度", en: "Dimension" })}</TableHead>
                <TableHead>{t({ zh: "旧值", en: "Before" })}</TableHead>
                <TableHead>{t({ zh: "新值", en: "After" })}</TableHead>
              </>
            ) : (
              <TableHead>
                {t({ zh: "释义 / 例句", en: "Meaning / example" })}
              </TableHead>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {entries.map((entry) => {
            if (side === "both") {
              const dimensions = entry.fields ?? []
              return dimensions.length > 0 ? (
                dimensions.map((dimension, index) => (
                  <TableRow key={`${entry.word_id}-${dimension}-${index}`}>
                    {index === 0 && (
                      <TableCell
                        rowSpan={dimensions.length}
                        className="font-semibold"
                      >
                        {entry.headword}
                      </TableCell>
                    )}
                    <TableCell>
                      <Badge variant="outline">
                        {t(diffDimensionLabel(dimension))}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-52 whitespace-normal break-words align-top text-muted-foreground">
                      {formatSnapshotField(entry.from_entry, dimension)}
                    </TableCell>
                    <TableCell className="max-w-52 whitespace-normal break-words align-top">
                      {formatSnapshotField(entry.to_entry, dimension)}
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow key={entry.word_id}>
                  <TableCell className="font-semibold">
                    {entry.headword}
                  </TableCell>
                  <TableCell colSpan={3} className="text-muted-foreground">
                    –
                  </TableCell>
                </TableRow>
              )
            }
            const snapshot = entryValue(entry, side)
            return (
              <TableRow key={entry.word_id}>
                <TableCell className="font-semibold">
                  {entry.headword}
                </TableCell>
                <TableCell className="max-w-72 whitespace-normal break-words align-top text-muted-foreground">
                  {formatSnapshotField(snapshot, "meaning")}
                  {formatSnapshotField(snapshot, "example") !== "–" && (
                    <span className="mt-0.5 block">
                      {formatSnapshotField(snapshot, "example")}
                    </span>
                  )}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
