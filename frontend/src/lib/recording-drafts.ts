/**
 * 录音草稿本地暂存（批次08B：刷新后恢复待上传录音）。
 *
 * 只持久化「已录完、等待上传或上传失败」的音频 Blob，不做录音中崩溃恢复。
 * 每条草稿绑定：用户（JWT sub）、课堂、会话、题型、题目、原幂等键、mime、
 * 时长与创建时间；不保存 token。跨账号按 owner 隔离，登出清除该账号草稿。
 *
 * 明确的边界（不宣称具备完整离线考试能力）：
 * - Safari 隐私模式/存储被拒时全部操作降级为 no-op（返回 "unavailable"），
 *   页面行为与没有草稿功能时完全一致（内存重传仍可用）；
 * - 本地过期/TTL/上限清理只删本地缓存，不影响服务器上的作答；
 * - 恢复上传不能突破服务端题窗门禁——服务器拒绝时结果以服务器为准。
 */

export const DRAFT_TTL_MS = 24 * 60 * 60 * 1000
export const MAX_DRAFTS_PER_OWNER = 5
export const MAX_DRAFTS_TOTAL_BYTES = 50 * 1024 * 1024

export type DraftItemType = "passage" | "repeat" | "question"

export interface RecordingDraftInput {
  owner: string
  classroomCode: string
  sessionId: string | null
  itemType: DraftItemType
  itemId: string
  idempotencyKey: string
  mimeType: string
  durationS: number
  blob: Blob
}

/** 列表展示用的元信息（不含 Blob 本体） */
export interface RecordingDraftMeta {
  key: string
  owner: string
  classroomCode: string
  sessionId: string | null
  itemType: DraftItemType
  itemId: string
  idempotencyKey: string
  mimeType: string
  durationS: number
  createdAt: number
  size: number
}

interface RecordingDraftRecord extends Omit<RecordingDraftMeta, "size"> {
  blob: Blob
}

export type DraftSaveResult = "saved" | "quota" | "unavailable"

const DB_NAME = "esa-recording-drafts"
const DB_VERSION = 1
const STORE = "drafts"

/** 复合主键：同账号同课堂同题同幂等键的草稿只有一份 */
export function draftKey(
  input: Omit<RecordingDraftInput, "blob" | "mimeType" | "durationS">,
): string {
  return [
    input.owner,
    input.classroomCode.toUpperCase(),
    input.sessionId ?? "",
    input.itemType,
    input.itemId,
    input.idempotencyKey,
  ].join("|")
}

// ── 时间源（测试可注入） ──
let clockNow: () => number = () => Date.now()
export function setDraftClockForTests(clock: () => number): void {
  clockNow = clock
}

// ── IndexedDB 工厂（测试可注入；隐私模式等读不到时降级） ──
let idbFactoryOverride: IDBFactory | null | undefined
export function setDraftIdbFactoryForTests(factory: IDBFactory | null): void {
  idbFactoryOverride = factory
  dbPromise = null
}

function factory(): IDBFactory | null {
  if (idbFactoryOverride !== undefined) return idbFactoryOverride
  return (globalThis as { indexedDB?: IDBFactory }).indexedDB ?? null
}

let dbPromise: Promise<IDBDatabase> | null = null

function openDb(): Promise<IDBDatabase> {
  if (!dbPromise) {
    dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
      const f = factory()
      if (!f) {
        reject(new Error("indexeddb-unavailable"))
        return
      }
      const request = f.open(DB_NAME, DB_VERSION)
      request.onupgradeneeded = () => {
        const db = request.result
        if (!db.objectStoreNames.contains(STORE)) {
          const store = db.createObjectStore(STORE, { keyPath: "key" })
          store.createIndex("by_owner", "owner")
        }
      }
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error ?? new Error("open-failed"))
      request.onblocked = () => reject(new Error("open-blocked"))
    }).catch((err: unknown) => {
      // 打开失败不缓存，下次调用重试（例如隐私模式误报后用户关闭）
      dbPromise = null
      throw err
    })
  }
  return dbPromise
}

function requestToPromise<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () =>
      reject(request.error ?? new Error("idb-request-failed"))
  })
}

function isQuotaError(err: unknown): boolean {
  return (
    err instanceof DOMException &&
    (err.name === "QuotaExceededError" || err.code === 22)
  )
}

function toRecord(
  input: RecordingDraftInput,
  createdAt: number,
): RecordingDraftRecord {
  return {
    key: draftKey(input),
    owner: input.owner,
    classroomCode: input.classroomCode.toUpperCase(),
    sessionId: input.sessionId,
    itemType: input.itemType,
    itemId: input.itemId,
    idempotencyKey: input.idempotencyKey,
    mimeType: input.mimeType,
    durationS: input.durationS,
    createdAt,
    blob: input.blob,
  }
}

function toMeta(record: RecordingDraftRecord): RecordingDraftMeta {
  const { blob, ...meta } = record
  return { ...meta, size: blob.size }
}

async function readOwnerRecords(
  db: IDBDatabase,
  owner: string,
): Promise<RecordingDraftRecord[]> {
  const tx = db.transaction(STORE, "readonly")
  const index = tx.objectStore(STORE).index("by_owner")
  const all = await requestToPromise(
    index.getAll(owner) as IDBRequest<RecordingDraftRecord[]>,
  )
  return all
}

function deleteKeys(db: IDBDatabase, keys: string[]): Promise<void> {
  if (keys.length === 0) return Promise.resolve()
  return new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite")
    const store = tx.objectStore(STORE)
    for (const key of keys) store.delete(key)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error ?? new Error("idb-delete-failed"))
    tx.onabort = () => reject(tx.error ?? new Error("idb-delete-aborted"))
  })
}

/**
 * 超出数量/容量上限时按最旧优先淘汰，返回应删除的 key。
 * incomingBytes 计入新草稿；skipKey 永不淘汰（正在保存的那条）。
 */
export function selectEvictions(
  drafts: RecordingDraftMeta[],
  incomingBytes: number,
  skipKey?: string,
): string[] {
  const sorted = [...drafts].sort((a, b) => a.createdAt - b.createdAt)
  const victims: string[] = []
  const kept = sorted.filter((d) => d.key !== skipKey)
  // 数量上限（新草稿计入后不超过 MAX）
  while (kept.length + 1 > MAX_DRAFTS_PER_OWNER) {
    const oldest = kept.shift()
    if (!oldest) break
    victims.push(oldest.key)
  }
  // 容量上限
  let total = kept.reduce((sum, d) => sum + d.size, 0) + incomingBytes
  while (total > MAX_DRAFTS_TOTAL_BYTES && kept.length > 0) {
    const oldest = kept.shift()
    if (!oldest) break
    total -= oldest.size
    victims.push(oldest.key)
  }
  return victims
}

async function purgeExpired(db: IDBDatabase): Promise<void> {
  const tx = db.transaction(STORE, "readwrite")
  const store = tx.objectStore(STORE)
  const cutoff = clockNow() - DRAFT_TTL_MS
  const all = await requestToPromise(
    store.getAll() as IDBRequest<RecordingDraftRecord[]>,
  )
  const expired = all
    .filter((record) => record.createdAt < cutoff)
    .map((record) => record.key)
  if (expired.length === 0) return
  await new Promise<void>((resolve, reject) => {
    // getAll 之后原事务已提交，删除需要新事务
    const deleteTx = db.transaction(STORE, "readwrite")
    const deleteStore = deleteTx.objectStore(STORE)
    for (const key of expired) deleteStore.delete(key)
    deleteTx.oncomplete = () => resolve()
    deleteTx.onerror = () => reject(deleteTx.error ?? new Error("purge-failed"))
  })
}

/** put 的可注入实现（测试模拟 QuotaExceededError 用） */
export interface DraftStoreDeps {
  putRecord?: (db: IDBDatabase, record: RecordingDraftRecord) => Promise<void>
}

const defaultPut = async (
  db: IDBDatabase,
  record: RecordingDraftRecord,
): Promise<void> => {
  await requestToPromise(
    db.transaction(STORE, "readwrite").objectStore(STORE).put(record),
  )
}

async function putWithRetry(
  db: IDBDatabase,
  record: RecordingDraftRecord,
  deps?: DraftStoreDeps,
): Promise<"saved" | "quota"> {
  const put = deps?.putRecord ?? defaultPut
  try {
    await put(db, record)
    return "saved"
  } catch (err) {
    if (!isQuotaError(err)) throw err
    // 配额不足：清掉本人其余草稿后重试一次；仍失败则明确降级
    const others = await readOwnerRecords(db, record.owner)
    await deleteKeys(
      db,
      others.filter((r) => r.key !== record.key).map((r) => r.key),
    ).catch(() => undefined)
    try {
      await put(db, record)
      return "saved"
    } catch (retryErr) {
      if (isQuotaError(retryErr)) return "quota"
      throw retryErr
    }
  }
}

/**
 * 保存一条待上传草稿。先清过期、按上限淘汰最旧，再写入；
 * QuotaExceededError 清本人其余草稿重试一次。任何环境级失败（无
 * IndexedDB/打开失败/未知异常）都返回 "unavailable"，绝不抛给调用方。
 */
export async function saveRecordingDraft(
  input: RecordingDraftInput,
  deps?: DraftStoreDeps,
): Promise<DraftSaveResult> {
  try {
    const db = await openDb()
    await purgeExpired(db).catch(() => undefined)
    const own = await readOwnerRecords(db, input.owner)
    const evictions = selectEvictions(
      own.map(toMeta),
      input.blob.size,
      draftKey(input),
    )
    await deleteKeys(db, evictions).catch(() => undefined)
    return await putWithRetry(db, toRecord(input, clockNow()), deps)
  } catch {
    return "unavailable"
  }
}

/**
 * 列出某账号在某课堂的全部草稿（新→旧）。内部先做过期清理；
 * 环境不可用时返回空数组（页面等同「无草稿」）。
 */
export async function listRecordingDrafts(
  owner: string,
  classroomCode: string,
): Promise<RecordingDraftMeta[]> {
  try {
    const db = await openDb()
    await purgeExpired(db).catch(() => undefined)
    const records = await readOwnerRecords(db, owner)
    return records
      .filter((r) => r.classroomCode === classroomCode.toUpperCase())
      .map(toMeta)
      .sort((a, b) => b.createdAt - a.createdAt)
  } catch {
    return []
  }
}

/** 取单条草稿（含 Blob），用于恢复上传 */
export async function getRecordingDraft(
  key: string,
): Promise<(RecordingDraftMeta & { blob: Blob }) | null> {
  try {
    const db = await openDb()
    const tx = db.transaction(STORE, "readonly")
    const record = await requestToPromise(
      tx.objectStore(STORE).get(key) as IDBRequest<
        RecordingDraftRecord | undefined
      >,
    )
    if (!record) return null
    return { ...toMeta(record), blob: record.blob }
  } catch {
    return null
  }
}

export async function deleteRecordingDraft(key: string): Promise<void> {
  try {
    const db = await openDb()
    await deleteKeys(db, [key])
  } catch {
    // 删除失败（环境不可用）静默：TTL 会兜底
  }
}

/** 上传被服务器接受后：清掉该题目的所有草稿（幂等键不同也算，防陈旧重复） */
export async function deleteDraftsForItem(
  owner: string,
  classroomCode: string,
  itemId: string,
): Promise<void> {
  try {
    const db = await openDb()
    const records = await readOwnerRecords(db, owner)
    const keys = records
      .filter(
        (r) =>
          r.classroomCode === classroomCode.toUpperCase() &&
          r.itemId === itemId,
      )
      .map((r) => r.key)
    await deleteKeys(db, keys)
  } catch {
    // 同上：TTL 兜底
  }
}

/** 登出清理：只清该账号的草稿（另一账号在同一设备上的草稿保留） */
export async function clearRecordingDrafts(owner: string): Promise<void> {
  try {
    const db = await openDb()
    const records = await readOwnerRecords(db, owner)
    await deleteKeys(
      db,
      records.map((r) => r.key),
    )
  } catch {
    // 环境不可用时无需清理
  }
}

/**
 * 当前草稿属主：JWT sub（后端 create_access_token 的 subject = 用户 id）。
 * 解析失败/无 token 返回 null——调用方应视为「草稿功能关闭」（fail closed，
 * 绝不把 A 账号的草稿算到 B 头上）。只在浏览器环境可用。
 */
export function currentDraftOwner(): string | null {
  if (typeof localStorage === "undefined") return null
  try {
    const token = localStorage.getItem("access_token")
    if (!token) return null
    const payload = token.split(".")[1]
    if (!payload) return null
    const b64 = payload.replace(/-/g, "+").replace(/_/g, "/")
    const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4)
    const json = JSON.parse(atob(padded)) as { sub?: unknown }
    return typeof json.sub === "string" && json.sub.length > 0 ? json.sub : null
  } catch {
    return null
  }
}
