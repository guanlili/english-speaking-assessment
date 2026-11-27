# 12 · CSV morphology 端到端复验证据（D1）

- 复验时间：2026-11-24（Asia/Shanghai）
- 分支：`fix/qa-vocab-regression-20261124`（commit `4e2a6e4`，PR #543）
- 环境：前端 Vite `http://本地服务`（修复 worktree `.qa-worktrees/qa-fixes/frontend`，PID 2257）；后端 `http://本地服务`；DB 容器 `本地 DB 容器`，端口 5433，库 `app`
- 浏览器：**独立 Playwright 无头上下文**（chromium headless shell 1148），未使用共享 Chrome；教师账号 `[本地测试账号]`，学校入口 `/s/seedpilot-01/login`
- 源 CSV：`backend/scripts/demo/vocab-demo-words.csv`（18 数据行，列 `headword,meaning_zh,part_of_speech,meaning_en,accepted_spellings,example_en,morphology`）

## 结论：基本通过（D1 入库链路已修复；存在 2 条遗留，见下）

| 检查项 | 预期 | 实测 | 判定 |
|---|---|---|---|
| 预览行数 | 18 行 | 18 行（`import-preview` 200，预览「有效 18 行」） | 通过 |
| 预览接口带 morphology | 14+ 可拼回词带拆解 | 15 行返回拆解（含 1 个不可拼回的 writer），3 行 JSON null | 通过 |
| 入库 morphology 非空 | 非空 15 行 | JSON 非空 **15**，JSON null 字面量 **3**（apple/banana/careless） | 通过（口径见下注） |
| 可拼回原词 | 14 个 | **14** 个可拼回；**1** 个不可拼回（writer）拆解仍入库，未被后端拒绝/置空 | 遗留 |
| 读回接口带 morphology | 前端预判需要 | `GET /vocabulary/books/{id}` 返回 18 词，**morphology 全为 null**（0/18 非空） | 遗留（见 14 号证据根因） |

## 新建词库

- 标题：`QA-FIX-CSV-morph-20261124`
- book_id：`[id]`
- scope：classroom；课堂 `SD100X`（`[id]`）
- `word_count=18`，POST `/vocabulary/books` 200

## 预览接口抽查（import-preview 响应，18 行）

| headword | 预览 morphology |
|---|---|
| teacher | teach + er（root/suffix） |
| helpful | help + ful |
| sunflower | sun + flower |
| bookmark | book + mark |
| notebook | note + book |
| preheat | pre + heat |
| unhappy | un + happy |
| rethink | re + think |
| kindness | kind + ness |
| sunlight | sun + light |
| rainbow | rain + bow |
| popcorn | pop + corn |
| teapot | tea + pot |
| disable | dis + able |
| writer | write + er（**不可拼回**：write+er = `writeer` ≠ writer） |
| apple / banana / careless | null（源 CSV 无 morphology） |

完整响应落盘：`scratch/preview-payload.json`；创建响应：`scratch/books-post-payload.json`。

## DB 落库核对（book `[id]`）

> 注：`morphology` 为 json 列，无源拆解时存的是 JSON `null` 字面量（并非 SQL NULL），故统计口径用 `morphology::text <> 'null'`。

- JSON 非空：**15**；JSON null 字面量：**3**；合计 18。
- 可拼回判定（拆解段 text 按序拼接 casefold 等于 headword，且 ≥2 段）：
  - 可拼回 **14**：bookmark, disable, helpful, kindness, notebook, popcorn, preheat, rainbow, rethink, sunflower, sunlight, teacher, teapot, unhappy
  - 不可拼回 **1**：`writer`（段 `write`+`er` → `writeer` ≠ `writer`），**拆解仍原样入库**，后端未拒绝也未置空；该词在 roots 素材判定中会被前端/后端 `morphologyAssembles` 判为不可用。
  - JSON null **3**：apple, banana, careless。

## 截图

- `12-csv-preview-fix.png`：预览 18 行，CSV 表头提示已含 morphology 列
- `12-csv-book-created.png`：创建后词单

## 遗留 / 风险

1. **writer 非法拆解未被入库校验拦截**：与任务预判「writer 的拆解应被后端拒绝」不符——实际仍入库但无效。建议后端在词法入库时按 `morphologyAssembles` 口径校验，不可拼回则置空并计入 invalid。
2. **读回接口剥除 morphology**（阻断 D3 UI 预判，详见 `14-prompt-availability-evidence.md`）：`attach_word_levels` 构造 `VocabularyWordPublic` 时未传 `morphology`，教师端词单拿到的词法全为 null。
