import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import type { PassageWithSentences } from "@/client"
import { AdminService } from "@/client"
import { ContentNavigation } from "@/components/Admin/ContentNavigation"
import { EditPassageDialog } from "@/components/Admin/Passages/EditPassageDialog"
import { NewPassageForm } from "@/components/Admin/Passages/NewPassageForm"
import {
  type PassageForm,
  toRequestBody,
} from "@/components/Admin/Passages/shared"
import { TopicGroups } from "@/components/Admin/Passages/TopicGroups"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import Pager from "@/components/Common/Pager"
import { invalidateContentQueries } from "@/components/Teaching/CopyContentButton"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { APP_NAME } from "@/config"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"
import { extractErrorMessage } from "@/utils"
export const Route = createFileRoute("/_layout/admin/passages")({
  component: PassagesAdmin,
  head: () => ({ meta: [{ title: `篇目管理 / Passages - ${APP_NAME}` }] }),
})

export function PassagesAdmin({ embedded = false }: { embedded?: boolean }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [keyword, setKeyword] = useState("")
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editing, setEditing] = useState<PassageWithSentences | null>(null)
  const [toDelete, setToDelete] = useState<PassageWithSentences | null>(null)

  // 服务端分页 + 服务端关键词（题库增长后不再整表拉取；limit=None 全量只留给组卷）
  const PAGE_SIZE = 20
  const [pageIndex, setPageIndex] = useState(0)
  const passagesQuery = useQuery({
    queryKey: ["admin", "passages", keyword, pageIndex],
    queryFn: () =>
      AdminService.listPassages({
        q: keyword.trim() || undefined,
        skip: pageIndex * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
  })
  const totalCount = passagesQuery.data?.count ?? 0
  useEffect(() => {
    setPageIndex(0)
  }, [])
  useEffect(() => {
    if (
      passagesQuery.isSuccess &&
      !passagesQuery.isPlaceholderData &&
      (passagesQuery.data?.data ?? []).length === 0 &&
      totalCount > 0 &&
      pageIndex > 0
    ) {
      setPageIndex(Math.max(0, Math.ceil(totalCount / PAGE_SIZE) - 1))
    }
  }, [
    passagesQuery.isSuccess,
    passagesQuery.isPlaceholderData,
    passagesQuery.data,
    totalCount,
    pageIndex,
  ])

  const unitsQuery = useQuery({
    queryKey: ["admin", "units"],
    queryFn: () => AdminService.listUnits(),
  })
  const topicsQuery = useQuery({
    queryKey: ["admin", "topics"],
    queryFn: () => AdminService.listTopics(),
  })
  const scenariosQuery = useQuery({
    queryKey: ["admin", "scenarios"],
    queryFn: () => AdminService.listScenarios(),
  })

  const invalidate = () => invalidateContentQueries(queryClient)

  const createMutation = useMutation({
    mutationFn: (form: PassageForm) =>
      AdminService.createPassage({ passageCreate: toRequestBody(form) }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "篇目已创建", en: "Passage created" }))
      invalidate()
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, form }: { id: string; form: PassageForm }) =>
      AdminService.updatePassage({
        passage_id: id,
        passageUpdate: toRequestBody(form),
      }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "篇目已更新", en: "Passage updated" }))
      setEditing(null)
      invalidate()
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => AdminService.deletePassage({ passage_id: id }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "已删除", en: "Deleted" }))
      setToDelete(null)
      invalidate()
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  const units = (unitsQuery.data ?? []).map((u) => ({
    id: u.id,
    title: u.title,
    topic: u.topic,
  }))

  return (
    <div className="flex flex-col gap-6">
      {!embedded && <ContentNavigation />}
      {!embedded && (
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {t(TERMS.typeReading)}
          </h1>
          <p className="text-muted-foreground">
            {t({
              zh: "未拆分的文章整篇一道题；拆分过的文章组卷时按句出题、学生逐句朗读。展开文章可查看正文和分句，也可管理配套的听句复述。",
              en: "An unsplit article is one read-aloud question; a split article becomes one question per sentence so students read aloud sentence by sentence. Expand an article to view its text and sentences, or manage its paired Listen & Repeat items.",
            })}
          </p>
        </div>
      )}

      <details className="rounded-xl border bg-card p-4">
        <summary className="cursor-pointer font-medium text-primary">
          {t({ zh: "新建篇目", en: "New Passage" })}
        </summary>
        <div className="mt-4">
          <NewPassageForm
            topics={topicsQuery.data ?? []}
            units={units}
            scenarioTopics={
              new Set(
                (scenariosQuery.data?.data ?? []).map((s) => s.topic ?? ""),
              )
            }
            pending={createMutation.isPending}
            onSubmit={(form) => createMutation.mutateAsync(form)}
          />
        </div>
      </details>
      <Input
        aria-label={t({ zh: "搜索篇目", en: "Search passages" })}
        placeholder={t({
          zh: "搜索篇目标题或主题…",
          en: "Search passage title or topic…",
        })}
        value={keyword}
        onChange={(event) => setKeyword(event.target.value)}
      />
      {passagesQuery.isPending ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : passagesQuery.isError ? (
        <div className="flex flex-col items-center gap-3 py-8 text-muted-foreground">
          <p>
            {t({ zh: "篇目列表加载失败。", en: "Failed to load passages." })}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void passagesQuery.refetch()}
          >
            {t({ zh: "重试", en: "Retry" })}
          </Button>
        </div>
      ) : (passagesQuery.data?.data ?? []).length === 0 ? (
        <p className="py-8 text-center text-muted-foreground">
          {keyword.trim()
            ? t({
                zh: "没有匹配的篇目，请换个关键词。",
                en: "No passages match — try another keyword.",
              })
            : t({
                zh: "还没有篇目，点击上方新建按钮开始备课。",
                en: "No passages yet — use the New Passage form above to start building.",
              })}
        </p>
      ) : (
        <>
          <TopicGroups
            passages={passagesQuery.data?.data ?? []}
            units={unitsQuery.data ?? []}
            expandedId={expandedId}
            onToggle={setExpandedId}
            onEdit={setEditing}
            onDelete={setToDelete}
            onMutated={invalidate}
          />
          {passagesQuery.isSuccess && totalCount > PAGE_SIZE && (
            <Pager
              pageIndex={pageIndex}
              pageSize={PAGE_SIZE}
              count={totalCount}
              isPlaceholder={passagesQuery.isPlaceholderData}
              onChange={setPageIndex}
            />
          )}
        </>
      )}

      <EditPassageDialog
        passage={editing}
        topics={topicsQuery.data ?? []}
        units={units}
        scenarioTopics={
          new Set((scenariosQuery.data?.data ?? []).map((s) => s.topic ?? ""))
        }
        pending={updateMutation.isPending}
        onClose={() => setEditing(null)}
        onSubmit={(form) => {
          if (editing) updateMutation.mutate({ id: editing.id, form })
        }}
      />

      <ConfirmDialog
        open={toDelete !== null}
        title={t({
          zh: `删除篇目「${toDelete?.title ?? ""}」？`,
          en: `Delete passage "${toDelete?.title ?? ""}"?`,
        })}
        description={t({
          zh: "删除会连带清掉它的复述句，正在练习中的学生下次会拿到别的篇目。此操作不可撤销。",
          en: "Deleting also removes its repeat sentences; students mid-practice will get a different passage next time. This cannot be undone.",
        })}
        confirmText={t({ zh: "删除篇目", en: "Delete Passage" })}
        onOpenChange={(next) => {
          if (!next) setToDelete(null)
        }}
        onConfirm={async () => {
          if (toDelete) await deleteMutation.mutateAsync(toDelete.id)
        }}
      />
    </div>
  )
}
