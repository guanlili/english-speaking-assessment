/**
 * 题库批量导入：后端稳定标识 → 双语展示。
 *
 * 后端 reason / detail 是中文稳定标识（同 detail 口径），前端在此映射成
 * 双语，英文界面（外教）也能看懂。未匹配的文案原样回落。
 */

import { extractErrorMessage } from "@/utils"
import type { BiString } from "./bi.ts"
import { ITEM_TYPE_LABELS } from "./terms.ts"

/** 题型 key（passage/repeat/question/instruction）→ 双语名。 */
export function questionBankTypeLabel(type: string): BiString {
  return ITEM_TYPE_LABELS[type] ?? { zh: type, en: type }
}

/** 取错误体里的原始 detail（blob 拦截器会把下载端点的错误响应也变成 Blob）。 */
async function rawErrorDetail(err: unknown): Promise<string> {
  const body = (err as { body?: unknown } | null)?.body
  if (body instanceof Blob) {
    try {
      const parsed = JSON.parse(await body.text()) as { detail?: unknown }
      if (typeof parsed.detail === "string") {
        return parsed.detail
      }
    } catch {
      // 非 JSON 错误体：交由通用回落
    }
    return ""
  }
  const detail = (body as { detail?: unknown } | undefined)?.detail
  if (typeof detail === "string") {
    return detail
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown }
    if (typeof first?.msg === "string") {
      return first.msg
    }
  }
  return ""
}

/**
 * 文件级错误的完整链路：原始 detail → 题库专用双语映射 → 通用回落。
 *
 * 必须先取原始 detail 再映射——extractErrorMessage 对未登记的中文 detail
 * 会先替换成英文通用文案，之后专用映射就永远匹配不上（评审 P2：外教在
 * 缺少题型列时只看到 Something went wrong，无法自行修正）。
 */
export async function questionBankErrorMessage(
  err: unknown,
): Promise<BiString> {
  const raw = await rawErrorDetail(err)
  if (raw) {
    const mapped = matchQuestionBankDetail(raw)
    if (mapped) {
      return mapped
    }
    return { zh: raw, en: extractErrorMessage(err) }
  }
  const fallback = extractErrorMessage(err)
  return { zh: fallback, en: fallback }
}

/** 行级问题原因（含疑似重复说明）→ 双语。 */
export function localizeQuestionImportIssue(reason: string): BiString {
  const table: Array<[RegExp, BiString | ((m: RegExpMatchArray) => BiString)]> =
    [
      [
        /^题型不能为空$/,
        { zh: "题型不能为空", en: "Question type is required" },
      ],
      [
        /^题型列的值无效：(.+)$/,
        (m) => ({
          zh: `题型列的值无效：${m[1]}`,
          en: `Unknown question type: ${m[1]}`,
        }),
      ],
      [/^标题不能为空$/, { zh: "标题不能为空", en: "Title is required" }],
      [
        /^正文不能为空$/,
        { zh: "正文不能为空", en: "Passage text is required" },
      ],
      [/^句子不能为空$/, { zh: "句子不能为空", en: "Sentence is required" }],
      [/^题目不能为空$/, { zh: "题目不能为空", en: "Question is required" }],
      [
        /^说明文字不能为空$/,
        { zh: "说明文字不能为空", en: "Instruction text is required" },
      ],
      [/^主题不能为空$/, { zh: "主题不能为空", en: "Topic is required" }],
      [
        /^(标题|主题|小标题|中文提示|句子|题目|说明文字)过长（>(\d+) 字符）$/,
        (m) => ({
          zh: m[0],
          en: `${m[1]} is too long (max ${m[2]} characters)`,
        }),
      ],
      [
        /^难度无效，可选：A2\/B1\/B2$/,
        { zh: "难度无效，可选：A2/B1/B2", en: "Invalid level; use A2/B1/B2" },
      ],
      [
        /^(建议秒数|作答秒数|秒数|可听次数|准备秒数)需为 (\d+)–(\d+) 之间的整数$/,
        (m) => ({
          zh: m[0],
          en: `${m[1]} must be a whole number between ${m[2]} and ${m[3]}`,
        }),
      ],
      [
        /^建议秒数需在 (\d+)–(\d+) 之间（考试题型支持长回答）$/,
        (m) => ({
          zh: m[0],
          en: `Seconds must be between ${m[1]} and ${m[2]} (exam tasks allow longer answers)`,
        }),
      ],
      [
        /^准备时间须在 10–180 秒之间$/,
        {
          zh: "准备时间须在 10–180 秒之间",
          en: "Prep time must be 10–180 seconds",
        },
      ],
      [
        /^状态无效，可选：启用\/停用$/,
        {
          zh: "状态无效，可选：启用/停用",
          en: "Invalid status; use 启用 or 停用",
        },
      ],
      [
        /^未知考试题型：(.+)$/,
        (m) => ({ zh: m[0], en: `Unknown exam type: ${m[1]}` }),
      ],
      [
        /^考试题型无效：(.+)$/,
        (m) => ({
          zh: m[0],
          en: `Exam type not allowed for this sheet: ${m[1]}`,
        }),
      ],
      [
        /^考试级别无效，可选：(.+)$/,
        (m) => ({ zh: m[0], en: `Invalid exam level; options: ${m[1]}` }),
      ],
      [
        /^未选择考试题型时不能单独设置级别\/话题卡\/准备时间$/,
        {
          zh: "未选择考试题型时不能单独设置级别/话题卡/准备时间",
          en: "Level, cue card or prep time requires an exam type",
        },
      ],
      [
        /^选择考试题型时需同时标注级别$/,
        {
          zh: "选择考试题型时需同时标注级别",
          en: "Exam type also needs a level",
        },
      ],
      [
        /^话题卡要点仅支持 IELTS Part 2 题型$/,
        {
          zh: "话题卡要点仅支持 IELTS Part 2 题型",
          en: "Cue cards are only for IELTS Part 2",
        },
      ],
      [
        /^音频链接格式不正确/,
        {
          zh: "音频链接格式不正确（须为本站音频链接）",
          en: "Invalid audio link (must be this site's audio URL)",
        },
      ],
      [
        /^单元匹配到多个同名单元，请改为精确的单元标题$/,
        {
          zh: "单元匹配到多个同名单元，请改为精确的单元标题",
          en: "Multiple units share this title; use the exact unit title",
        },
      ],
      [
        /^挂靠篇目匹配到多个同名篇目，请先重命名区分$/,
        {
          zh: "挂靠篇目匹配到多个同名篇目，请先重命名区分",
          en: "Multiple passages share this title; rename them first",
        },
      ],
      [
        /^疑似重复：同名同正文篇目已存在，但难度\/秒数等配置不同$/,
        {
          zh: "疑似重复：同名同正文篇目已存在，但配置不同",
          en: "Possible duplicate: same passage exists with different settings",
        },
      ],
      [
        /^疑似重复：相同正文已存在于其他篇目$/,
        {
          zh: "疑似重复：相同正文已存在于其他篇目",
          en: "Possible duplicate: this text already exists in another passage",
        },
      ],
      [
        /^疑似重复：相同句子已存在但配置不同$/,
        {
          zh: "疑似重复：相同句子已存在但配置不同",
          en: "Possible duplicate: this sentence exists with different settings",
        },
      ],
      [
        /^疑似重复：该主题下已有相同题目但配置不同$/,
        {
          zh: "疑似重复：该主题下已有相同题目但配置不同",
          en: "Possible duplicate: same question in this topic with different settings",
        },
      ],
      [
        /^疑似重复：该题目已存在于其他主题$/,
        {
          zh: "疑似重复：该题目已存在于其他主题",
          en: "Possible duplicate: this question exists under another topic",
        },
      ],
      [
        /^疑似重复：相同说明文字已存在但标题\/秒数不同$/,
        {
          zh: "疑似重复：相同说明文字已存在但标题/秒数不同",
          en: "Possible duplicate: this instruction exists with different title/seconds",
        },
      ],
    ]
  for (const [pattern, mapped] of table) {
    const match = reason.match(pattern)
    if (match) {
      return typeof mapped === "function" ? mapped(match) : mapped
    }
  }
  return { zh: reason, en: reason }
}

/** 文件级错误 detail（422/413 toast 用）→ 双语；未匹配返回 null（走通用回落）。 */
export function matchQuestionBankDetail(detail: string): BiString | null {
  const missing = detail.match(/^工作表「(.+)」缺少必填列：(.+)$/)
  if (missing) {
    return {
      zh: `「${missing[1]}」缺少必填列：${missing[2]}`,
      en: `Sheet "${missing[1]}" is missing required columns: ${missing[2]}`,
    }
  }
  const overRows = detail.match(/^工作表「(.+)」有效区共 (\d+) 行/)
  if (overRows) {
    return {
      zh: `「${overRows[1]}」有效区 ${overRows[2]} 行，超过 2000 行上限；若因整列设置格式导致，请清除多余格式或把数据复制到新模板`,
      en: `Sheet "${overRows[1]}" spans ${overRows[2]} rows (limit 2000). If caused by whole-column formatting, clear it or copy data into a fresh template`,
    }
  }
  const overCols = detail.match(/^工作表「(.+)」有 (\d+) 列/)
  if (overCols) {
    return {
      zh: `「${overCols[1]}」列数过多（${overCols[2]} 列），请使用标准模板的列`,
      en: `Sheet "${overCols[1]}" has ${overCols[2]} columns; keep the template columns`,
    }
  }
  const overCell = detail.match(/^(.+)「(.*)」的(\w+)超过 Excel 单元格/)
  if (overCell) {
    return {
      zh: `${overCell[1]}「${overCell[2]}」内容超过 Excel 单元格 32767 字符上限，请改用 CSV 格式导出（无损）`,
      en: `${overCell[1]} "${overCell[2]}" exceeds Excel's 32,767-character cell limit; export as CSV instead (lossless)`,
    }
  }
  const table: Array<[RegExp, BiString]> = [
    [
      /^文件超过 5MB 上限$/,
      { zh: "文件超过 5MB 上限", en: "File exceeds the 5MB limit" },
    ],
    [/^文件为空$/, { zh: "文件为空", en: "The file is empty" }],
    [
      /^文件必须是 UTF-8 编码$/,
      { zh: "文件必须是 UTF-8 编码", en: "The file must be UTF-8 encoded" },
    ],
    [
      /^仅支持 \.xlsx 或 \.csv 文件$/,
      {
        zh: "仅支持 .xlsx 或 .csv 文件",
        en: "Only .xlsx or .csv files are supported",
      },
    ],
    [
      /^Excel 文件无法解析/,
      {
        zh: "Excel 文件无法解析，请重新保存后重试",
        en: "Cannot read this Excel file; re-save it and try again",
      },
    ],
    [
      /^工作表「(.+)」无法识别题型/,
      {
        zh: "有工作表无法识别题型，请勿重命名模板工作表",
        en: "A worksheet name is not recognized; keep the template sheet names",
      },
    ],
    [
      /^CSV 缺少题型列$/,
      { zh: "CSV 缺少「题型」列", en: "CSV is missing the Type column" },
    ],
    [
      /^CSV 表头缺少(.+)必填列：(.+)$/,
      {
        zh: "CSV 表头缺少必填列",
        en: "CSV header is missing required columns",
      },
    ],
    [
      /^行数超过上限/,
      {
        zh: "行数超过上限（2000 行），请分批导入",
        en: "Over 2000 rows; split into smaller files",
      },
    ],
    [
      /^文件中没有可导入的数据行$/,
      { zh: "文件中没有可导入的数据行", en: "No data rows found in the file" },
    ],
    [
      /^未找到可识别的工作表/,
      {
        zh: "未找到可识别的工作表（文章朗读/听句复述/情景问答/题目说明）",
        en: "No recognizable worksheets (Read Aloud / Listen & Repeat / Scenario Q&A / Instruction)",
      },
    ],
    [
      /^导出行数超过上限/,
      {
        zh: "导出行数过多，请缩小筛选范围",
        en: "Too many rows to export; narrow the filters",
      },
    ],
    [
      /^导入失败，已整体回滚/,
      {
        zh: "导入失败，已整体回滚，请重试",
        en: "Import failed and was fully rolled back; try again",
      },
    ],
  ]
  for (const [pattern, mapped] of table) {
    if (pattern.test(detail)) {
      return mapped
    }
  }
  return null
}
