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

export const Route = createFileRoute("/_layout/admin/units")({
  component: UnitsAdmin,
  head: () => ({ meta: [{ title: `练习分组 - ${APP_NAME}` }] }),
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
      showSuccessToast(editing ? "单元已更新" : "单元已创建")
      setFormOpen(false)
      invalidate()
    },
    onError: (error) => showErrorToast(`保存失败：${error.message}`),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => AdminService.deleteUnit({ unitId: id }),
    onSuccess: () => {
      showSuccessToast("单元已删除（其下篇目转为未归属）")
      setToDelete(null)
      invalidate()
    },
    onError: (error) => showErrorToast(`删除失败：${error.message}`),
  })

  const formValid =
    form.title.trim().length > 0 &&
    form.topic.trim().length > 0 &&
    form.order_index >= 0

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">练习分组</h1>
          <p className="text-muted-foreground">
            把配套内容整理为一组，课堂里选中这组内容即可安排练习。每组建议只保留一篇启用的材料。
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus />
          新建单元
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">全部单元</CardTitle>
          <CardDescription>
            按关卡顺序排列；「篇目数」为 0 的单元指派后学生没有可练内容。
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
              <p>单元列表加载失败。</p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void unitsQuery.refetch()}
              >
                重试
              </Button>
            </div>
          ) : (unitsQuery.data ?? []).length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              还没有单元，先新建分组，再在文章朗读或听句复述中选择此分组。
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">顺序</TableHead>
                  <TableHead>标题</TableHead>
                  <TableHead>主题</TableHead>
                  <TableHead>篇目数</TableHead>
                  <TableHead>状态</TableHead>
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
                        <Badge variant="destructive">0 · 缺篇目</Badge>
                      ) : (
                        <Badge variant="secondary">
                          {unit.passage_count ?? 0} 篇
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {unit.is_active ? (
                        <Badge variant="outline">启用</Badge>
                      ) : (
                        <Badge variant="secondary">已停用</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`编辑 ${unit.title}`}
                          onClick={() => openEdit(unit)}
                        >
                          <Pencil />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`删除 ${unit.title}`}
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
            <DialogTitle>{editing ? "编辑单元" : "新建单元"}</DialogTitle>
            <DialogDescription>
              关卡顺序决定学生端解锁次序；主题建议从已有列表里选。
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="unit-order">排列顺序</Label>
                <Input
                  id="unit-order"
                  type="number"
                  min={0}
                  value={form.order_index}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      order_index: Number(e.target.value),
                    }))
                  }
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label>主题</Label>
                <TopicPicker
                  value={form.topic}
                  topics={topicsQuery.data ?? []}
                  onChange={(topic) => setForm((f) => ({ ...f, topic }))}
                />
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="unit-title">单元标题</Label>
              <Input
                id="unit-title"
                value={form.title}
                placeholder="例如：Unit 1 · Pets"
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
              启用（学生端可见；停用后不再出现在主题探索）
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFormOpen(false)}>
              取消
            </Button>
            <LoadingButton
              disabled={!formValid}
              loading={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              {editing ? "保存" : "创建"}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={toDelete !== null}
        title={`删除单元「${toDelete?.title ?? ""}」？`}
        description="删除后该单元下的篇目会变成“未归属”，学生主题探索里也不再出现这一主题。此操作不可撤销。"
        confirmText="删除单元"
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
