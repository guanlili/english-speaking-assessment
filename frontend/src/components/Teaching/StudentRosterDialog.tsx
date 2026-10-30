import { useMutation, useQuery } from "@tanstack/react-query"
import { Pencil, RotateCcw, Trash2, UserMinus } from "lucide-react"
import { useState } from "react"
import { ApiError, StudentsService } from "@/client"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
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
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"

function StudentRosterDialog({
  classroomId,
  open,
  onOpenChange,
}: {
  classroomId: string
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { t } = useI18n()
  const rosterQuery = useQuery({
    queryKey: ["students", classroomId],
    queryFn: () => StudentsService.listStudents({ classroom_id: classroomId }),
    enabled: open,
  })
  const [removeTarget, setRemoveTarget] = useState<string | null>(null)
  const [bulkConfirm, setBulkConfirm] = useState(false)
  const [bulkDone, setBulkDone] = useState<number | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [forceDeleteTarget, setForceDeleteTarget] = useState<string | null>(
    null,
  )
  const [renameTarget, setRenameTarget] = useState<{
    id: string
    name: string
  } | null>(null)
  const [renameValue, setRenameValue] = useState("")

  const renameMutation = useMutation({
    mutationFn: ({ studentId, name }: { studentId: string; name: string }) =>
      StudentsService.updateStudent({
        student_id: studentId,
        studentUpdate: { display_name: name },
      }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "姓名已更新", en: "Name updated" }))
      setRenameTarget(null)
      void rosterQuery.refetch()
    },
    onError: (error) => showErrorToast(extractErrorMessage(error)),
  })

  const deleteMutation = useMutation({
    mutationFn: ({
      studentId,
      deleteHistory,
    }: {
      studentId: string
      deleteHistory?: boolean
    }) =>
      StudentsService.removeStudent({
        student_id: studentId,
        purge: true,
        delete_history: deleteHistory,
      }),
    onSuccess: (res) => {
      showSuccessToast(
        t({
          zh: res.message?.includes("容量") ? res.message : "已从名单删除",
          en: "Deleted from the roster",
        }),
      )
      setDeleteTarget(null)
      setForceDeleteTarget(null)
      void rosterQuery.refetch()
    },
    onError: (error) => {
      // 有作答历史：后端 409 阻断 → 升级到强确认（携带删除历史重试）
      const body = error instanceof ApiError ? error.body : null
      const detail =
        body &&
        typeof body === "object" &&
        "detail" in body &&
        typeof body.detail === "string"
          ? body.detail
          : ""
      if (detail.includes("作答记录") && deleteMutation.variables?.studentId) {
        setDeleteTarget(null)
        setForceDeleteTarget(deleteMutation.variables.studentId)
        return
      }
      showErrorToast(extractErrorMessage(error))
      setDeleteTarget(null)
    },
  })

  const resetMutation = useMutation({
    mutationFn: (studentId: string) =>
      StudentsService.resetStudentPassword({ student_id: studentId }),
    onSuccess: () => {
      showSuccessToast(
        t({
          zh: "已重置为默认密码 brs123456",
          en: "Password reset to the default brs123456",
        }),
      )
    },
    onError: (error) => showErrorToast(extractErrorMessage(error)),
  })

  const resetPendingId = resetMutation.isPending
    ? (resetMutation.variables as string | undefined)
    : null

  const bulkResetMutation = useMutation({
    mutationFn: () =>
      StudentsService.bulkResetPasswords({ classroom_id: classroomId }),
    onSuccess: (res) => {
      setBulkDone(res.reset)
      showSuccessToast(
        res.skipped
          ? t({
              zh: `已重置 ${res.reset} 个账号为默认密码 brs123456；跳过 ${res.skipped} 个（非学生账号或跨班共享，需管理员处理）`,
              en: `${res.reset} account(s) reset to the default password brs123456; ${res.skipped} skipped (non-student or shared across classes — needs an administrator).`,
            })
          : t({
              zh: `已重置 ${res.reset} 个账号为默认密码 brs123456`,
              en: `${res.reset} account(s) reset to the default password brs123456`,
            }),
      )
    },
    onError: (error) => showErrorToast(extractErrorMessage(error)),
  })

  const removeMutation = useMutation({
    mutationFn: (studentId: string) =>
      StudentsService.removeStudent({ student_id: studentId }),
    onSuccess: () => {
      showSuccessToast(
        t({
          zh: "已移出课堂（档案与历史保留）",
          en: "Removed from the classroom (profile and history kept)",
        }),
      )
      setRemoveTarget(null)
      void rosterQuery.refetch()
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `移出失败：${error.message}`,
          en: `Failed to remove: ${error.message}`,
        }),
      ),
  })

  const students = rosterQuery.data ?? []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {t({ zh: "学生名单", en: "Student Roster" })}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "学号账号与状态；忘记密码时重置为默认密码 brs123456。",
              en: "Student ID accounts and status; reset to the default password brs123456 when forgotten.",
            })}
          </DialogDescription>
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              {t({
                zh: "学生可自行修改密码；重置后已修改的密码会被覆盖回默认。",
                en: "Students can change their own passwords; a reset overwrites changed passwords with the default.",
              })}
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setBulkConfirm(true)}
            >
              {t({
                zh: "全部重置为默认密码",
                en: "Reset All to Default Password",
              })}
            </Button>
          </div>
          {bulkDone !== null && (
            <div className="rounded-md border bg-muted/40 p-3 text-sm">
              {t({
                zh: `已重置 ${bulkDone} 个账号为默认密码 brs123456。`,
                en: `${bulkDone} account(s) reset to the default password brs123456.`,
              })}
            </div>
          )}
        </DialogHeader>
        {rosterQuery.isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : students.length === 0 ? (
          <p className="py-6 text-center text-muted-foreground">
            {t({
              zh: "还没有学生账号，先「导入学生」。",
              en: 'No student accounts yet — start with "Import Students".',
            })}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t({ zh: "姓名", en: "Name" })}</TableHead>
                <TableHead>{t({ zh: "学号", en: "Student ID" })}</TableHead>
                <TableHead>{t({ zh: "状态", en: "Status" })}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {students.map((s) => (
                <TableRow key={s.student.id}>
                  <TableCell className="font-medium">
                    {s.student.display_name}
                  </TableCell>
                  <TableCell className="font-mono">
                    {s.username ?? "—"}
                  </TableCell>
                  <TableCell>
                    {s.username ? (
                      <Badge variant="outline">
                        {t({ zh: "在班", en: "Enrolled" })}
                      </Badge>
                    ) : (
                      <Badge variant="secondary">
                        {t({ zh: "已移出", en: "Unlinked" })}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      {s.username && (
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={t({
                            zh: "重置密码",
                            en: "Reset Password",
                          })}
                          disabled={resetPendingId === s.student.id}
                          onClick={() => {
                            resetMutation.mutate(s.student.id)
                          }}
                        >
                          <RotateCcw className="size-3.5" />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t({
                          zh: `修改 ${s.student.display_name} 的姓名`,
                          en: `Rename ${s.student.display_name}`,
                        })}
                        onClick={() => {
                          setRenameValue(s.student.display_name)
                          setRenameTarget({
                            id: s.student.id,
                            name: s.student.display_name,
                          })
                        }}
                      >
                        <Pencil className="size-3.5" />
                      </Button>
                      {s.username && (
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={t({
                            zh: "移出课堂",
                            en: "Remove from classroom",
                          })}
                          onClick={() => setRemoveTarget(s.student.id)}
                        >
                          <UserMinus className="size-3.5" />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t({
                          zh: "从名单删除",
                          en: "Delete from roster",
                        })}
                        onClick={() => setDeleteTarget(s.student.id)}
                      >
                        <Trash2 className="size-3.5 text-destructive" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </DialogContent>
      <Dialog
        open={renameTarget !== null}
        onOpenChange={(v) => {
          if (!v) setRenameTarget(null)
        }}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "修改姓名", en: "Rename Student" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "只修改本班显示名；学号与登录密码不变（修改学号需删除后重新导入）。",
                en: "Changes the display name in this classroom only; the student ID and password stay (to change the ID, delete and re-import).",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="rename-student">
              {t({ zh: "姓名", en: "Name" })}
            </Label>
            <Input
              id="rename-student"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              maxLength={64}
            />
          </div>
          <DialogFooter>
            <LoadingButton
              disabled={
                !renameValue.trim() || renameValue.trim() === renameTarget?.name
              }
              loading={renameMutation.isPending}
              onClick={() => {
                if (renameTarget)
                  renameMutation.mutate({
                    studentId: renameTarget.id,
                    name: renameValue.trim(),
                  })
              }}
            >
              {t({ zh: "保存", en: "Save" })}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={deleteTarget !== null}
        title={t({
          zh: "从名单删除该学生？",
          en: "Delete this student from the roster?",
        })}
        description={t({
          zh: "删除的是本班档案（释放班级容量），不删除学号账号；如需彻底删除该学生的账号，请联系管理员在「用户与权限」中操作。如该生有练习记录，会再要求一次确认。",
          en: "This deletes the classroom profile (freeing a class-size slot), not the account itself. To delete the student's account entirely, ask an administrator via Users & Permissions. If they have practice history, you will be asked to confirm again.",
        })}
        confirmText={t({
          zh: "删除",
          en: "Delete",
        })}
        destructive
        onOpenChange={(next) => {
          if (!next) setDeleteTarget(null)
        }}
        onConfirm={async () => {
          if (deleteTarget)
            await deleteMutation.mutateAsync({
              studentId: deleteTarget,
              deleteHistory: false,
            })
        }}
      />
      <ConfirmDialog
        open={forceDeleteTarget !== null}
        title={t({
          zh: "该学生有作答记录，仍要删除？",
          en: "This student has answer history — delete anyway?",
        })}
        description={t({
          zh: "确认后将删除该学生在本班的全部练习记录、成绩与游戏化数据，此操作不可恢复。",
          en: "Confirming permanently deletes all of this student's practice records, scores and progress in this classroom. This cannot be undone.",
        })}
        confirmText={t({
          zh: "删除全部记录",
          en: "Delete All Records",
        })}
        destructive
        onOpenChange={(next) => {
          if (!next) setForceDeleteTarget(null)
        }}
        onConfirm={async () => {
          if (forceDeleteTarget)
            await deleteMutation.mutateAsync({
              studentId: forceDeleteTarget,
              deleteHistory: true,
            })
        }}
      />
      <ConfirmDialog
        open={removeTarget !== null}
        title={t({
          zh: "把该学生移出课堂？",
          en: "Remove this student from the classroom?",
        })}
        description={t({
          zh: "仅解除账号与课堂的绑定；练习档案与作答历史保留，重新导入相同学号可找回。",
          en: "Only unlinks the account from the classroom; practice profiles and answer history are kept, and re-importing the same student ID restores access.",
        })}
        confirmText={t({
          zh: "移出课堂",
          en: "Remove from Classroom",
        })}
        onOpenChange={(next) => {
          if (!next) setRemoveTarget(null)
        }}
        onConfirm={async () => {
          if (removeTarget) await removeMutation.mutateAsync(removeTarget)
        }}
      />

      <Dialog
        open={bulkConfirm}
        onOpenChange={(v) => {
          setBulkConfirm(v)
          if (!v) setBulkDone(null)
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>
              {t({
                zh: "全部重置为默认密码？",
                en: "Reset all to the default password?",
              })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "课堂内全部已绑定账号的密码将统一重置为默认密码 brs123456（学生自行修改过的密码也会被覆盖）。确定继续？",
                en: "All linked accounts in this classroom will be reset to the default password brs123456 (including passwords students changed themselves). Continue?",
              })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBulkConfirm(false)}>
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
            <LoadingButton
              loading={bulkResetMutation.isPending}
              onClick={() => {
                bulkResetMutation.mutate()
                setBulkConfirm(false)
              }}
            >
              {t({ zh: "重置全部", en: "Reset All" })}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Dialog>
  )
}

export default StudentRosterDialog
