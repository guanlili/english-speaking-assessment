import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Megaphone, Pencil, Plus, Trash2 } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type ChangelogPublic, ChangelogService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import useAuth from "@/hooks/useAuth"
import {
  changelogQueryKey,
  markChangelogSeen,
  useChangelog,
} from "@/hooks/useChangelog"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import { formatDate } from "@/lib/time"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/changelog")({
  component: ChangelogPage,
  head: () => ({
    meta: [
      {
        title: "平台更新 | What's New | BELP",
      },
    ],
  }),
})

const KIND_OPTIONS = ["feature", "improvement", "fix"] as const
const NONE_KIND = "none"

/** 类型标签的纯函数映射（hook 不可在循环/回调里调用，故不用 hook）。 */
function kindLabel(
  kind: string | null,
  t: ReturnType<typeof useI18n>["t"],
): string | null {
  return kind === "feature"
    ? t({ zh: "新功能", en: "New Feature" })
    : kind === "improvement"
      ? t({ zh: "优化", en: "Improvement" })
      : kind === "fix"
        ? t({ zh: "修复", en: "Fix" })
        : null
}

function KindBadge({ kind }: { kind: string | null }) {
  const { t } = useI18n()
  const label = kindLabel(kind, t)
  if (!label) return null
  return (
    <Badge
      className={
        kind === "feature"
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/10"
          : kind === "improvement"
            ? "border-sky-500/40 bg-sky-500/10 text-sky-700 hover:bg-sky-500/10"
            : "border-amber-500/40 bg-amber-500/10 text-amber-700 hover:bg-amber-500/10"
      }
    >
      {label}
    </Badge>
  )
}

// 校验消息随语言切换：schema 在组件内按当前语言重建
function buildFormSchema(t: ReturnType<typeof useI18n>["t"]) {
  return z.object({
    day: z
      .string()
      .min(1, { message: t({ zh: "请选择发布日期", en: "Pick a date" }) }),
    kind: z.string(),
    title_zh: z.string().min(1, {
      message: t({ zh: "请输入中文标题", en: "Chinese title is required" }),
    }),
    title_en: z.string().min(1, {
      message: t({ zh: "请输入英文标题", en: "English title is required" }),
    }),
    body_zh: z.string(),
    body_en: z.string(),
  })
}

type FormData = z.infer<ReturnType<typeof buildFormSchema>>

function toFormValues(entry?: ChangelogPublic): FormData {
  return {
    day: entry?.day ?? new Date().toISOString().slice(0, 10),
    kind: entry?.kind ?? NONE_KIND,
    title_zh: entry?.title_zh ?? "",
    title_en: entry?.title_en ?? "",
    body_zh: entry?.body_zh ?? "",
    body_en: entry?.body_en ?? "",
  }
}

function EntryDialog({
  open,
  onOpenChange,
  editing,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  editing: ChangelogPublic | null
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const schema = useMemo(() => buildFormSchema(t), [t])

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: toFormValues(editing ?? undefined),
  })

  useEffect(() => {
    if (open) form.reset(toFormValues(editing ?? undefined))
  }, [open, editing, form])

  const mutation = useMutation({
    mutationFn: (data: FormData) => {
      const body = {
        day: data.day,
        kind: data.kind === NONE_KIND ? null : data.kind,
        title_zh: data.title_zh,
        title_en: data.title_en,
        body_zh: data.body_zh || null,
        body_en: data.body_en || null,
      }
      return editing
        ? ChangelogService.updateChangelogEntry({
            entry_id: editing.id,
            changelogUpdate: body,
          })
        : ChangelogService.createChangelogEntry({ changelogCreate: body })
    },
    onSuccess: () => {
      showSuccessToast(
        editing
          ? t({ zh: "更新日志已保存", en: "Entry updated" })
          : t({ zh: "更新日志已发布", en: "Entry published" }),
      )
      onOpenChange(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: changelogQueryKey })
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {editing
              ? t({ zh: "编辑更新日志", en: "Edit Entry" })
              : t({ zh: "发布平台更新", en: "Publish Update" })}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "教师与管理员会在「平台更新」看到这条内容。",
              en: "Teachers and admins will see this under What's New.",
            })}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit((data) => mutation.mutate(data))}>
            <div className="grid gap-4 py-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <FormField
                  control={form.control}
                  name="day"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        {t({ zh: "发布日期", en: "Date" })}{" "}
                        <span className="text-destructive">*</span>
                      </FormLabel>
                      <FormControl>
                        <Input type="date" {...field} required />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="kind"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{t({ zh: "类型", en: "Type" })}</FormLabel>
                      <Select
                        value={field.value}
                        onValueChange={field.onChange}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value={NONE_KIND}>
                            {t({ zh: "无标签", en: "No label" })}
                          </SelectItem>
                          {KIND_OPTIONS.map((kind) => (
                            <SelectItem key={kind} value={kind}>
                              {kindLabel(kind, t)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
              <FormField
                control={form.control}
                name="title_zh"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {t({ zh: "中文标题", en: "Chinese Title" })}{" "}
                      <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input {...field} required />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="title_en"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {t({ zh: "英文标题", en: "English Title" })}{" "}
                      <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input {...field} required />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="body_zh"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {t({ zh: "中文说明", en: "Chinese Notes" })}
                    </FormLabel>
                    <FormControl>
                      <Textarea rows={3} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="body_en"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {t({ zh: "英文说明", en: "English Notes" })}
                    </FormLabel>
                    <FormControl>
                      <Textarea rows={3} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline" disabled={mutation.isPending}>
                  {t({ zh: "取消", en: "Cancel" })}
                </Button>
              </DialogClose>
              <LoadingButton type="submit" loading={mutation.isPending}>
                {editing
                  ? t({ zh: "保存", en: "Save" })
                  : t({ zh: "发布", en: "Publish" })}
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

function ChangelogPage() {
  const { t, lang } = useI18n()
  const { user } = useAuth()
  const isAdmin = !!user?.is_superuser
  const { data, isPending, isError } = useChangelog()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<ChangelogPublic | null>(null)
  const [toDelete, setToDelete] = useState<ChangelogPublic | null>(null)

  // 进入页面即视为已读：只写水位，不 invalidate——invalidate 会改 data
  // 引用再触发本 effect，形成循环；红点在侧栏下次重渲染（路由切换）时自然消失
  useEffect(() => {
    if (data !== undefined) {
      markChangelogSeen(data[0]?.day)
    }
  }, [data])

  const deleteMutation = useMutation({
    mutationFn: (entry: ChangelogPublic) =>
      ChangelogService.deleteChangelogEntry({ entry_id: entry.id }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "已删除", en: "Deleted" }))
      setToDelete(null)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: changelogQueryKey })
    },
  })

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Megaphone aria-hidden="true" className="size-5 text-primary" />
          <h1 className="text-xl font-semibold">
            {t({ zh: "平台更新", en: "What's New" })}
          </h1>
        </div>
        {isAdmin && (
          <Button
            onClick={() => {
              setEditing(null)
              setDialogOpen(true)
            }}
          >
            <Plus className="mr-2 size-4" />
            {t({ zh: "发布更新", en: "Publish Update" })}
          </Button>
        )}
      </div>

      {isPending && (
        <p className="py-16 text-center text-muted-foreground">
          {t({ zh: "加载中…", en: "Loading…" })}
        </p>
      )}
      {isError && (
        <p className="py-16 text-center text-destructive">
          {t({
            zh: "加载失败，请刷新重试。",
            en: "Failed to load. Please retry.",
          })}
        </p>
      )}
      {data && data.length === 0 && (
        <p className="py-16 text-center text-muted-foreground">
          {t({
            zh: "暂无平台更新。",
            en: "No updates yet.",
          })}
        </p>
      )}

      {data && data.length > 0 && (
        <ol className="relative space-y-4 border-l border-border pl-5 sm:pl-6">
          {data.map((entry) => (
            <li key={entry.id} className="relative">
              <span
                aria-hidden="true"
                className="absolute -left-[27px] top-4 size-2.5 rounded-full border-2 border-background bg-primary sm:-left-[31px]"
              />
              <article className="rounded-lg border bg-card p-4">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <time
                    dateTime={entry.day}
                    className="text-xs font-medium text-muted-foreground"
                  >
                    {formatDate(entry.day, lang)}
                  </time>
                  <KindBadge kind={entry.kind} />
                </div>
                <h2 className="text-base font-semibold leading-snug">
                  {lang === "zh" ? entry.title_zh : entry.title_en}
                </h2>
                {(lang === "zh"
                  ? (entry.body_zh ?? entry.body_en)
                  : (entry.body_en ?? entry.body_zh)) && (
                  <p className="mt-1.5 whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
                    {lang === "zh"
                      ? (entry.body_zh ?? entry.body_en)
                      : (entry.body_en ?? entry.body_zh)}
                  </p>
                )}
                {isAdmin && (
                  <div className="mt-3 flex justify-end gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-9 px-3"
                      onClick={() => {
                        setEditing(entry)
                        setDialogOpen(true)
                      }}
                    >
                      <Pencil aria-hidden="true" className="mr-1 size-3.5" />
                      {t({ zh: "编辑", en: "Edit" })}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-9 px-3 text-destructive hover:text-destructive"
                      onClick={() => setToDelete(entry)}
                    >
                      <Trash2 aria-hidden="true" className="mr-1 size-3.5" />
                      {t({ zh: "删除", en: "Delete" })}
                    </Button>
                  </div>
                )}
              </article>
            </li>
          ))}
        </ol>
      )}

      <EntryDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editing={editing}
      />

      <Dialog
        open={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "删除这条更新？", en: "Delete this entry?" })}
            </DialogTitle>
            <DialogDescription>
              {lang === "zh" ? toDelete?.title_zh : toDelete?.title_en}
              {" · "}
              {toDelete ? formatDate(toDelete.day, lang) : ""}
              {t({
                zh: "，删除后不可恢复。",
                en: " This cannot be undone.",
              })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline">
                {t({ zh: "取消", en: "Cancel" })}
              </Button>
            </DialogClose>
            <LoadingButton
              variant="destructive"
              loading={deleteMutation.isPending}
              onClick={() => toDelete && deleteMutation.mutate(toDelete)}
            >
              {t({ zh: "删除", en: "Delete" })}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default ChangelogPage
