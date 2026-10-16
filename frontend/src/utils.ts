import { AxiosError } from "axios"
import type { ApiError } from "./client"
import { readStoredLang } from "./lib/bi.ts"

/**
 * 后端 detail 文案 → 双语展示文案（双语准则：detail 是稳定标识，
 * 用户提示在前端映射；新增后端 detail 时在这里补两列）。
 * zh 列缺省回退原文；en 列缺省回退通用英文（不把中文透给英文用户）。
 */
const DETAIL_MESSAGES: Record<string, { zh?: string; en: string }> = {
  "Reading sentences changed": {
    zh: "正文已变化，请刷新后重新设置逐句时长。",
    en: "The article has changed. Refresh before setting sentence durations.",
  },
  "Reading sentence durations count mismatch": {
    zh: "句子数量已变化，请刷新后重新设置逐句时长。",
    en: "The sentence count has changed. Refresh and set the sentence durations again.",
  },
  课后作业不能开启模考: {
    zh: "课后作业不能开启模考。请关掉模考后再发布为课后作业。",
    en: "Homework cannot be an exam. Turn off exam mode, then publish it as homework.",
  },
  没有课后作业: {
    zh: "老师还没有布置课后作业。",
    en: "No homework has been assigned yet.",
  },
  课后作业只接受题目列表: {
    zh: "课后作业只能按题目发布或撤回。",
    en: "Homework can only be published or withdrawn with a question list.",
  },
  "Automated exam audio missing: ": {
    zh: "自动考试包含缺少音频的题目。请在题库的「考试流程设置」中上传或生成音频，再重新发布。",
    en: "Some exam items have no audio. Upload or generate audio in Exam flow settings, then publish again.",
  },
  "Incorrect email or password": {
    zh: "邮箱或密码不正确，请重新输入",
    en: "Incorrect email or password",
  },
  "Inactive user": {
    zh: "账号已停用，请联系学校管理员",
    en: "This account is disabled. Please contact your school administrator.",
  },
  "Open user registration is forbidden on this server": {
    zh: "暂未开放自助注册，请联系学校管理员开通账号",
    en: "Self-registration is not available. Please contact your school administrator.",
  },
  "The user with this email already exists in the system": {
    zh: "该邮箱已注册，请直接登录或找回密码",
    en: "This email is already registered. Sign in or recover your password.",
  },
  "Invalid token": {
    zh: "重置链接无效或已过期，请重新申请",
    en: "This reset link is invalid or expired. Please request a new one.",
  },
  账号或密码不正确: { en: "Incorrect account or password" },
  "登录尝试过于频繁，请 5 分钟后再试": {
    en: "Too many sign-in attempts. Please try again in 5 minutes.",
  },
  该操作仅限学生账号: { en: "This action is for student accounts only." },
  请先登录: { en: "Please sign in first." },
  请先登录后再提交课堂作答: {
    en: "Please sign in before submitting class work.",
  },
  "录音太短（不足 1 秒），请再录一次": {
    en: "Recording is too short (under 1 second). Please record again.",
  },
  "音频超过 ": { en: "Audio exceeds the size limit." },
  "音频为空，请再录一次": { en: "Audio is empty. Please record again." },
  "音频文件无效或损坏，请重新录音": {
    en: "The audio file is invalid or corrupted. Please record again.",
  },
  "文件中没有音频音轨，请重新录音": {
    en: "No audio track found in the file. Please record again.",
  },
  "音轨数异常，请重新录音": {
    en: "Unusual audio channels. Please record again.",
  },
  "评分队列繁忙，请稍后重试": {
    en: "The scoring queue is busy. Please try again shortly.",
  },
  "评分服务暂时不可用，请稍后重试或联系老师": {
    en: "Scoring is temporarily unavailable. Please retry later or contact your teacher.",
  },
  "题目内容已不可用，请联系老师重新发布": {
    en: "This item is no longer available. Please ask your teacher to republish.",
  },
  题目不存在: { en: "Item not found." },
  题目不在本次发布练习内: {
    en: "This item is not part of the published exercise.",
  },
  该句不在本轮练习内: { en: "This sentence is not in the current round." },
  该句不在本轮篇目内: { en: "This sentence is not in this round's passage." },
  "没有权限：该练习轮不属于你本人": {
    en: "No permission: this practice round belongs to someone else.",
  },
  "没有权限：您不是该作答所属课堂的授权教师": {
    en: "No permission: you are not the authorized teacher for this classroom.",
  },
  "没有权限：只能管理自己课堂的学生": {
    en: "No permission: you can only manage students in your own classroom.",
  },
  "没有权限：只能重置学生账号的密码": {
    en: "No permission: only student account passwords can be reset.",
  },
  "没有权限：只能修改自己创建的题目": {
    en: "No permission: you can only edit questions you created.",
  },
  "没有权限：主题下有其他老师的题目，不能删除": {
    en: "No permission: this topic contains other teachers' questions and can't be deleted.",
  },
  "没有权限：不能替换其他老师题目的考试音频": {
    en: "No permission: you can't replace the exam audio on another teacher's item.",
  },
  "没有权限：该学生账号同时属于其他教师的班级，请联系管理员重置": {
    en: "No permission: this student also belongs to another teacher's class. Ask an administrator to reset the password.",
  },
  "作答凭证已失效，请重新录音后提交": {
    en: "This recording token is no longer valid. Please record and submit again.",
  },
  "该场考试已开考过，请返回考试入口继续": {
    en: "This exam has already been started. Please re-enter from the exam page.",
  },
  "Session not found": {
    zh: "练习会话不存在",
    en: "Practice session not found.",
  },
  "Classroom not found": { zh: "课堂不存在", en: "Classroom not found." },
  "Student not found": { zh: "学生档案不存在", en: "Student not found." },
  "课堂内已有学生作答记录，不能删除；如需停用请联系管理员在后台操作": {
    en: "This classroom has student submissions and cannot be deleted. Ask an administrator to deactivate it instead.",
  },
  "有正在评分中的作答，请稍后再删除": {
    en: "Answers are still being scored. Wait for scoring to finish before deleting.",
  },
  本题作答时间已结束或尚未开始: {
    en: "This item's answer window has ended or has not started yet.",
  },
  "邮件找回暂不可用，请联系学校管理员重置密码": {
    en: "Email recovery is unavailable. Please ask your school administrator to reset your password.",
  },
  // 学生导入逐行报错（多班归属：同名加入本班，异名/非学生账号仍阻断）
  "该学号已存在，但姓名与已有账号不一致": {
    en: "This student ID already exists with a different name. Please check the roster.",
  },
  该学号已被非学生账号使用: {
    en: "This student ID is taken by a non-student account.",
  },
  班级人数已满: {
    en: "This class is full. Ask the teacher to adjust the class size.",
  },
  学号为空: { en: "Student ID is empty." },
  学号不能包含空格等空白字符: {
    en: "Student ID cannot contain spaces or other whitespace.",
  },
  名单内学号重复: { en: "Duplicate student ID in the list." },
  "班级人数已满，请联系老师调整课堂容量": {
    en: "This class is full. Ask the teacher to adjust the class size.",
  },
  班级人数上限不能低于当前已有档案数: {
    en: "The size limit cannot go below the current roster size.",
  },
  该学生在本班有作答记录: {
    en: "This student has answer history in this classroom.",
  },
  该姓名在本班已被使用: {
    en: "This name is already used in this classroom.",
  },
  管理员密码不正确: {
    en: "Admin password incorrect — deletion denied.",
  },
  "Not Found": { zh: "资源不存在", en: "Not found." },
}

/** 后端文案（detail/导入行错误）→ 当前语言展示文案；双语准则的前端映射点。 */
export function localizedDetail(detail: string): string {
  const lang = readStoredLang()
  const exact = DETAIL_MESSAGES[detail]
  if (exact) {
    return lang === "en" ? exact.en : (exact.zh ?? detail)
  }
  // 前缀匹配（如 "音频超过 20MB 上限" 这类动态拼接的 detail）
  for (const [prefix, pair] of Object.entries(DETAIL_MESSAGES)) {
    if (detail.startsWith(prefix)) {
      const message = lang === "en" ? pair.en : (pair.zh ?? detail)
      if (prefix === "Automated exam audio missing: ") {
        const positions = detail.slice(prefix.length)
        return `${message} ${lang === "en" ? "Positions in the published list:" : "题单位置："}${positions}`
      }
      return message
    }
  }
  if (lang === "en") {
    // 英文用户不透出中文原文（含任何非 ASCII 字符即视为不可读）
    const asciiOnly = ![...detail].some((ch) => ch.charCodeAt(0) > 127)
    return asciiOnly ? detail : "Something went wrong. Please try again."
  }
  return detail
}

export function extractErrorMessage(err: unknown): string {
  const lang = readStoredLang()
  if (err instanceof AxiosError) {
    return err.code === "ECONNABORTED"
      ? lang === "en"
        ? "Request timed out. Please try again later."
        : "请求超时，请稍后重试"
      : lang === "en"
        ? "Network error. Please check your connection and retry."
        : "网络连接异常，请检查网络后重试"
  }

  const body = (err as ApiError | null)?.body as
    | { detail?: string | Array<{ msg: string }> }
    | undefined
  const errDetail = body?.detail
  if (Array.isArray(errDetail) && errDetail.length > 0) {
    return localizedDetail(errDetail[0].msg)
  }
  if (typeof errDetail === "string") {
    return localizedDetail(errDetail)
  }
  return lang === "en"
    ? "The service is temporarily unavailable. Please try again later."
    : "服务暂时不可用，请稍后重试"
}

export const handleError = function (
  this: (msg: string) => void,
  err: ApiError,
) {
  const errorMessage = extractErrorMessage(err)
  this(errorMessage)
}

export const getInitials = (name: string): string => {
  return name
    .split(" ")
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase()
}

export function safeLocalStorageGet<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

export function safeLocalStorageSet(key: string, value: unknown): boolean {
  try {
    localStorage.setItem(key, JSON.stringify(value))
    return true
  } catch {
    return false
  }
}

export function randomId(): string {
  // crypto.randomUUID 仅在安全上下文（HTTPS/localhost）可用：纯 HTTP 部署下是
  // undefined，点"开始录音"会直接 TypeError。降级到时间戳+随机数
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}
