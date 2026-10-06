import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Pencil, Plus, Trash2 } from "lucide-react"
import { useState } from "react"
import { AdminService } from "@/client"
import { TopicPicker } from "@/components/Admin/TopicPicker"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
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
import { LoadingButton } from "@/components/ui/loading-button"
import { NumberInput } from "@/components/ui/number-input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { APP_NAME } from "@/config"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"

export const Route = createFileRoute("/_layout/admin/units")({
  component: UnitsAdmin,
  head: () => ({ meta: [{ title: `单元管理 / Units - ${APP_NAME}` }] }),
})

interface UnitRow {
  id: string
  order_index: number
  title: string
  topic: string
  is_active: boolean
  passage_count?: number
}

const emptyForm = { order_index: 0, title: "", topic: "", is_active: true }

export function UnitsAdmin() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const unitsQuery = useQuery({
    queryKey: ["admin", "units"],
    queryFn: () => AdminService.listUnits(),
  })
  const topicsQuery = useQuery({
    queryKey: ["admin", "topics"],
    queryFn: () => AdminService.listTopics(),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "units"] })
    void queryClient.invalidateQueries({ queryKey: ["admin", "topics"] })
    void queryClient.invalidateQueries({ queryKey: ["teacher"] })
  }

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<UnitRow | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [toDelete, setToDelete] = useState<UnitRow | null>(null)

  const openCreate = () => {
    setEditing(null)
    setForm({ ...emptyForm, order_index: (unitsQuery.data ?? []).length })
    setFormOpen(true)
  }

  const openEdit = (unit: UnitRow) => {
    setEditing(unit)
    setForm({
      order_index: unit.order_index,
      title: unit.title,
      topic: unit.topic,
      is_active: unit.is_active,
    })
    setFormOpen(true)
  }

  const saveMutation = useMutation({
    mutationFn: () => {
      const body = {
        order_index: form.order_index,
        title: form.title.trim(),
        topic: form.topic.trim(),
        is_active: form.is_active,
      }
      return editing
        ? AdminService.updateUnit({ unitId: editing.id, requestBody: body })
        : AdminService.createUnit({ requestBody: body })
    },
    onSuccess: () => {
      showSuccessToast(
        editing
          ? t({ zh: "单元已更新", en: "Unit updated" })
          : t({ zh: "单元已创建", en: "Unit created" }),
      )
      setFormOpen(false)
      invalidate()
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `保存失败：${error.message}`,
          en: `Save failed: ${error.message}`,
        }),
      ),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => AdminService.deleteUnit({ unitId: id }),
    onSuccess: () => {
      showSuccessToast(
        t({
          zh: "单元已删除（其下篇目转为未归属）",
          en: "Unit deleted (its passages are now unassigned)",
        }),
      )
      setToDelete(null)
      invalidate()
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `删除失败：${error.message}`,
          en: `Delete failed: ${error.message}`,
        }),
      ),
  })

  const formValid =
    form.title.trim().length > 0 &&
    form.topic.trim().length > 0 &&
    form.order_index >= 0

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {t({ zh: "单元管理", en: "Unit Management" })}
          </h1>
          <p className="text-muted-foreground">
            {t({
              zh: "把一个单元的配套内容整理为一组，课堂里选中该单元即可安排练习。每个单元建议只保留一篇启用的篇目。",
              en: "Group a unit's content together so a class can pick the unit and start practicing. Keep one enabled passage per unit.",
            })}
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus />
          {t({ zh: "新建单元", en: "New Unit" })}
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({ zh: "全部单元", en: "All Units" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "按单元顺序排列；「篇目数」为 0 的单元指派后学生没有可练内容。",
              en: "Ordered by unit sequence; units with 0 passages leave students nothing to practice once assigned.",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {unitsQuery.isPending ? (
            <div className="flex flex-col gap-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : unitsQuery.isError ? (
            <div className="flex flex-col items-center gap-3 py-8 text-muted-foreground">
              <p>
                {t({ zh: "单元列表加载失败。", en: "Failed to load units." })}
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void unitsQuery.refetch()}
              >
                {t({ zh: "重试", en: "Retry" })}
              </Button>
            </div>
          ) : (unitsQuery.data ?? []).length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              {t({
                zh: "还没有单元，先新建一个单元，再在文章朗读或听句复述中选择此单元。",
                en: "No units yet — create one, then assign it from Read Aloud or Listen & Repeat.",
              })}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">
                    {t({ zh: "顺序", en: "Order" })}
                  </TableHead>
                  <TableHead>{t({ zh: "标题", en: "Title" })}</TableHead>
                  <TableHead>{t({ zh: "主题", en: "Topic" })}</TableHead>
                  <TableHead>{t({ zh: "篇目数", en: "Passages" })}</TableHead>
                  <TableHead>{t({ zh: "状态", en: "Status" })}</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(unitsQuery.data ?? []).map((unit) => (
                  <TableRow key={unit.id}>
                    <TableCell className="font-mono">
                      {unit.order_index}
                    </TableCell>
                    <TableCell className="font-medium">{unit.title}</TableCell>
                    <TableCell>{unit.topic}</TableCell>
                    <TableCell>
                      {(unit.passage_count ?? 0) === 0 ? (
                        <Badge variant="destructive">
                          {t({ zh: "0 · 缺篇目", en: "0 · No passage" })}
                        </Badge>
                      ) : (
                        <Badge variant="secondary">
                          {t({
                            zh: `${unit.passage_count ?? 0} 篇`,
                            en: `${unit.passage_count ?? 0} ${
                              (unit.passage_count ?? 0) === 1
                                ? "passage"
                                : "passages"
                            }`,
                          })}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {unit.is_active ? (
                        <Badge variant="outline">
                          {t({ zh: "启用", en: "Enabled" })}
                        </Badge>
                      ) : (
                        <Badge variant="secondary">
                          {t({ zh: "已停用", en: "Disabled" })}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={t({
                            zh: `编辑 ${unit.title}`,
                            en: `Edit ${unit.title}`,
                          })}
                          onClick={() => openEdit(unit)}
                        >
                          <Pencil />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={t({
                            zh: `删除 ${unit.title}`,
                            en: `Delete ${unit.title}`,
                          })}
                          onClick={() => setToDelete(unit)}
                        >
                          <Trash2 className="text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editing
                ? t({ zh: "编辑单元", en: "Edit Unit" })
                : t({ zh: "新建单元", en: "New Unit" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "单元顺序决定学生端自主练习的推进次序；主题建议从已有列表里选。",
                en: "Unit order drives the sequence of self practice for students; pick a topic from the existing list when possible.",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="unit-order">
                  {t({ zh: "排列顺序", en: "Order" })}
                </Label>
                <NumberInput
                  id="unit-order"
                  min={0}
                  value={form.order_index}
                  onValueChange={(order_index) =>
                    setForm((f) => ({ ...f, order_index }))
                  }
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label>{t({ zh: "主题", en: "Topic" })}</Label>
                <TopicPicker
                  value={form.topic}
                  topics={topicsQuery.data ?? []}
                  onChange={(topic) => setForm((f) => ({ ...f, topic }))}
                />
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="unit-title">
                {t({ zh: "单元标题", en: "Unit Title" })}
              </Label>
              <Input
                id="unit-title"
                value={form.title}
                placeholder={t({
                  zh: "例如：Unit 1 · Pets",
                  en: "e.g. Unit 1 · Pets",
                })}
                onChange={(e) =>
                  setForm((f) => ({ ...f, title: e.target.value }))
                }
              />
            </div>
            <div className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={form.is_active}
                onCheckedChange={(checked) =>
                  setForm((f) => ({ ...f, is_active: checked === true }))
                }
              />
              {t({
                zh: "启用（学生端可见；停用后不再出现在主题探索）",
                en: "Enabled (visible to students; once disabled it leaves topic exploration)",
              })}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFormOpen(false)}>
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
            <LoadingButton
              disabled={!formValid}
              loading={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              {editing
                ? t({ zh: "保存", en: "Save" })
                : t({ zh: "创建", en: "Create" })}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={toDelete !== null}
        title={t({
          zh: `删除单元「${toDelete?.title ?? ""}」？`,
          en: `Delete unit "${toDelete?.title ?? ""}"?`,
        })}
        description={t({
          zh: "删除后该单元下的篇目会变成“未归属”，学生主题探索里也不再出现这一主题。此操作不可撤销。",
          en: 'Its passages become "unassigned" and the topic leaves students\' topic exploration. This cannot be undone.',
        })}
        confirmText={t({ zh: "删除单元", en: "Delete Unit" })}
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
