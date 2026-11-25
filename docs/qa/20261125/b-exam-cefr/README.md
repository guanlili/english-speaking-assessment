# #517 扩展区 + CEFR 标签 — QA 截图矩阵（2026-11-25）

本目录归档 issue #517「扩展区 + CEFR 标签」在**本地隔离环境**完成的真实浏览器截图。全部页面来自本机 dev 前端（vite 5180 → 本地后端 8033 → 本地 Postgres 5433 开发库 `app`），不连接生产；账号、班级、词库均为本地 demo 合成数据（租户 `vocabdemo`，课堂 `VOCDEMO1`）。

## 视口与语言

- 视口三档：**1180×900**（桌面）、**820×900**（平板）、**390×844**（手机，mobile）。
- 语言两档：`zh`（中文）、`en`（英文）；文件名 `<surface>-<lang>-<width>.png`。
- 触控目标 ≥44px、表单字号 ≥16px；三档宽度 390 / 820 / 1180 均已覆盖。

## 截图清单

### 1. 教师词库详情（管理员视角，`/admin/vocabbooks` → `[DEMO] Advanced Exam Prep`）

展示考试标签 + CEFR 档位筛选（审核状态 / 考试 / 档位），词条标签列同时呈现 exam tags 与 CEFR 徽标。

| 文件 | 视口 | 语言 | 页面 |
|---|---|---|---|
| `teacher-books-zh-1180.png` | 1180×900 | 中文 | 词库管理 · 高级词库详情 · 词条表 |
| `teacher-books-zh-820.png` | 820×900 | 中文 | 同上（筛选换行、表格横向滑动） |
| `teacher-books-zh-390.png` | 390×844 | 中文 | 同上（单列、横向滑动提示） |
| `teacher-books-en-1180.png` | 1180×900 | 英文 | Word Books · Advanced Exam Prep · word table |
| `teacher-books-en-820.png` | 820×900 | 英文 | 同上 |
| `teacher-books-en-390.png` | 390×844 | 英文 | 同上 |

### 2. 扩展区 · 高级备考词（教师视角，`/t/VOCDEMO1/vocab`，布置任务面板内）

高级词独立分区；可按考试标签 / CEFR 档位筛选、按词头搜索；选择目标词库（或新建班级词库）后勾选转入。面板文案明示：转入走同一审核与授权校验；CEFR 只是词条内容标签，不代表学生水平。

| 文件 | 视口 | 语言 | 页面 |
|---|---|---|---|
| `teacher-advanced-panel-zh-1180.png` | 1180×900 | 中文 | 扩展区 · 高级备考词 · 筛选 / 转入目标 / 勾选列表 |
| `teacher-advanced-panel-zh-820.png` | 820×900 | 中文 | 同上（筛选换行、两列词条） |
| `teacher-advanced-panel-zh-390.png` | 390×844 | 中文 | 同上（单列、筛选纵向堆叠） |
| `teacher-advanced-panel-en-1180.png` | 1180×900 | 英文 | Advanced Exam Prep · filters / target book / checklist |
| `teacher-advanced-panel-en-820.png` | 820×900 | 英文 | 同上 |
| `teacher-advanced-panel-en-390.png` | 390×844 | 英文 | 同上 |

### 3. 学生词卡（学生视角，`/vocab/VOCDEMO1/books` → Advanced Exam Prep）

学生侧只读展示 **CEFR 档位徽标**（B2 / C1 / C2），**不下发、不展示 exam tags**；无「你的等级是 X」类评定或推断文案。

| 文件 | 视口 | 语言 | 页面 |
|---|---|---|---|
| `student-card-zh-1180.png` | 1180×900 | 中文 | 词库浏览 · 高级词库 · 单词卡（仅 CEFR） |
| `student-card-zh-820.png` | 820×900 | 中文 | 同上（两列） |
| `student-card-zh-390.png` | 390×844 | 中文 | 同上（单列） |
| `student-card-en-1180.png` | 1180×900 | 英文 | Word Books · word cards (CEFR badge only) |
| `student-card-en-820.png` | 820×900 | 英文 | 同上 |
| `student-card-en-390.png` | 390×844 | 英文 | 同上 |

## 口径与红线（截图对应验证点）

- **CEFR 是内容标签，不是测评结论**：学生词卡仅标注词条档位；界面不出现学生水平评定、不做「测出 CEFR」的推断。
- **扩展区转入门禁**：转入必须命中 SAT/ACT/GRE 高级标签、`review_status=approved`，并通过教材 / 授权校验；demo 来源可免授权但仍需审核通过。未通过审核或缺授权的词条由服务端拒绝，同库已收词条自动跳过。
- **快照稳定**：已发布任务按发布快照展示；旧快照缺少 `exam_tags` / `cefr_band` 字段时安全回落为空，不破坏旧任务。
- **mock 数据边界**：高级词全部 `source_type=demo`、`approved`，置于独立公共演示书 `[DEMO] Advanced Exam Prep`；标签与档位仅为本地演示分类，不构成真实考试认证或「官方词表」，不得导入生产。

## 复现命令（本地 dev，非生产）

```bash
# 种子：153 个高级备考词（SAT/ACT/GRE 为主）
cd backend
PYTHONPATH=. ENVIRONMENT=local POSTGRES_SERVER=localhost POSTGRES_PORT=5433 \
  .venv/bin/python scripts/demo_vocab/seed_demo.py
# 清理：按本地 demo 租户收敛，高级词书 / 词条 / 条目 / 快照全部清除，可重复执行
PYTHONPATH=. ENVIRONMENT=local POSTGRES_SERVER=localhost POSTGRES_PORT=5433 \
  .venv/bin/python scripts/demo_vocab/cleanup_demo.py
```

种子脚本守卫：host 必须为 `localhost` / `127.0.0.1`、库名 `app`，`ENVIRONMENT=production` 拒跑；不连接生产库。
