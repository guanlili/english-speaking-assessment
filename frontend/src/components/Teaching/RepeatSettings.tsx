import { useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"
import { AdminService, type RepeatSentence } from "@/client"
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

export function RepeatSettings({
  sentence,
  onSaved,
}: {
  sentence: RepeatSentence
  onSaved: () => void
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState(sentence.text)
  const [seconds, setSeconds] = useState(sentence.suggested_seconds ?? 8)
  const [replays, setReplays] = useState(sentence.replay_limit ?? 3)
  const save = useMutation({
    mutationFn: () =>
      AdminService.updateSentence({
        sentenceId: sentence.id ?? "",
        requestBody: {
          ...sentence,
          text: text.trim(),
          audio_url: text.trim() === sentence.text ? sentence.audio_url : null,
          suggested_seconds: seconds,
          replay_limit: replays,
        },
      }),
    onSuccess: () => {
      toast.success("复述题设置已保存")
      setOpen(false)
      onSaved()
    },
    onError: () => toast.error("保存失败，请重试"),
  })
  const valid =
    text.trim().length > 0 &&
    Number.isInteger(seconds) &&
    seconds >= 3 &&
    seconds <= 60 &&
    Number.isInteger(replays) &&
    replays >= 0 &&
    replays <= 9
  return (
    <>
      <Button
        size="sm"
        variant="outline"
        onClick={() => {
          setText(sentence.text)
          setSeconds(sentence.suggested_seconds ?? 8)
          setReplays(sentence.replay_limit ?? 3)
          setOpen(true)
        }}
      >
        设置
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => !save.isPending && setOpen(next)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>编辑听句复述</DialogTitle>
            <DialogDescription>
              设置句子、作答时间与可听次数。0
              表示不限次数；修改句子后需重新配置标准音。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor={`sentence-text-${sentence.id}`}>英文句子</Label>
              <Input
                id={`sentence-text-${sentence.id}`}
                value={text}
                onChange={(event) => setText(event.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor={`sentence-seconds-${sentence.id}`}>
                  作答秒数（3–60）
                </Label>
                <Input
                  id={`sentence-seconds-${sentence.id}`}
                  type="number"
                  min={3}
                  max={60}
                  value={seconds}
                  onChange={(event) => setSeconds(Number(event.target.value))}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor={`sentence-replays-${sentence.id}`}>
                  可听次数（0–9）
                </Label>
                <Input
                  id={`sentence-replays-${sentence.id}`}
                  type="number"
                  min={0}
                  max={9}
                  value={replays}
                  onChange={(event) => setReplays(Number(event.target.value))}
                />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={save.isPending}
              onClick={() => setOpen(false)}
            >
              取消
            </Button>
            <LoadingButton
              loading={save.isPending}
              disabled={!valid}
              onClick={() => save.mutate()}
            >
              保存设置
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
