/** 限听播放：开始后的错误要退出播放态；过期请求不能再动当前题。 */

export function mayControlPlayback(
  active: boolean,
  requestedItemId: string,
  currentItemId: string,
): boolean {
  return active && requestedItemId === currentItemId
}

export function playbackAfterSignal(
  _playing: boolean,
  signal: "start" | "error" | "end",
): { playing: boolean; notify: boolean } {
  if (signal === "start") return { playing: true, notify: false }
  if (signal === "end") return { playing: false, notify: false }
  return { playing: false, notify: true }
}
