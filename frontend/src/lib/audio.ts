/**
 * 全站音频复用层：同一 src 只创建一个 HTMLAudioElement 并缓存，
 * 重复播放零下载零解码；配合预载让「听音」首点即响。
 *
 * 缓存有上限（超出时淘汰最早的已暂停元素，正在播放的不动）。
 * 语义与 `new Audio(src)` 直接播放的差别：再次点击同一 src 时从头重启
 * （而非新旧两路叠音）；页面卸载时需 stopAudio 防串音。
 * 限次播放（LimitedListenButton）的服务端计数逻辑不经此层，行为不变。
 */

const MAX_CACHED_AUDIO = 48

const cache = new Map<string, HTMLAudioElement>()

/** 缓存超过上限时淘汰最早的已暂停元素（正在播放的不动） */
function evictIfNeeded() {
  if (cache.size <= MAX_CACHED_AUDIO) return
  for (const [src, el] of cache) {
    if (cache.size <= MAX_CACHED_AUDIO) break
    if (el.paused) cache.delete(src)
  }
}

/** 获取（或创建并缓存）可复用的音频元素；preload=auto 创建即请求资源 */
export function getAudio(src: string): HTMLAudioElement {
  let audio = cache.get(src)
  if (!audio) {
    audio = new Audio(src)
    audio.preload = "auto"
    cache.set(src, audio)
    evictIfNeeded()
  }
  return audio
}

/** 从头播放缓存音频；返回的 Promise 在被浏览器拦截时 reject，调用方自行提示 */
export function playAudio(src: string): Promise<void> {
  const audio = getAudio(src)
  audio.currentTime = 0
  return audio.play().then(() => undefined)
}

/** 停止某个音频（切题/卸载时防串音）；未在播则无操作 */
export function stopAudio(src: string | null | undefined) {
  if (!src) return
  const audio = cache.get(src)
  if (audio && !audio.paused) {
    audio.pause()
    audio.currentTime = 0
  }
}

/** 预载：提前建元素触发资源请求，让学生点「听音」时零等待。静默失败不打扰 */
export function preloadAudio(sources: Array<string | null | undefined>) {
  for (const src of sources) {
    if (src) getAudio(src)
  }
}
