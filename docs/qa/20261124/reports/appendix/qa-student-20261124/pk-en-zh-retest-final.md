# D-S3 修复最终真机复验 · 2026-11-24（前端 + 后端）

## 1. 结论：**通过（真机端到端）**

PR #543 后端补透出 commit `87c5980` 已落到本地后端容器并 reload（健康检查 200）。5176 修复分支真机对局中：

- **en_zh 作答前题面显示英文 headword**（首题 `apple`，选项为中文释义）；
- **zh_en 题面仍为中文释义**（`香蕉`），选项英文单词，`headword=null`，未泄英文答案；
- 接口契约与真机渲染一致，D-S3 端到端关闭。

| 层面 | 结果 | 说明 |
|---|---|---|
| 后端补丁 | 已生效 | 容器 `/app/backend/app/services/vocabulary_pk.py` `_item_view`：`headword` 在 `answer is not None` 或 `prompt_type == "en_zh"` 时透出；`zh_en/cloze/roots` 作答前保持 `null` 防泄题 |
| 前端分流 | 已生效 | 5176 下发 `PkArena.tsx`：en_zh 读 headword，zh_en 读 meaning_zh |
| 真机 en_zh（作答前） | **通过** | 第 1/5 题题面 `apple`；选项 阳光/善意/苹果/重新思考（中文释义） |
| 真机 zh_en（防泄题） | **通过** | 第 2/5 题题面 `香蕉`；选项 disable/banana/writer/teacher；题面不含英文答案 |
| 后端回归单测 | 通过（PR 自述） | `test_en_zh_prompt_exposes_headword_before_answer` |

## 2. 环境与账号（本地隔离）

- 前端 `http://本地服务`（修复分支 Vite，未碰 5175/生产）；后端 `http://本地服务`；DB `app`。
- 租户 `seedpilot-01`，课堂 `SD100X`；词库 `[id]`（18 词）。
- 教师 `[本地测试账号]`（API 开/关厅）；s10001 浏览器真实点击；s10002 API 入队配对。本地测试密码 `[本地测试口令已移除]`。
- 本次大厅 `[id]`（5 题，30 秒/题，en_zh + zh_en）；对局 `[id]`。测完大厅已关闭。

## 3. 真机观测记录

### 3.1 第 1 题（item 0，en_zh，作答前）— 通过

- 接口：`prompt_type=en_zh`，`headword=apple`，`meaning_zh=苹果`；未作答。
- 真机页面：**题面 `apple`**；选项 `A. 阳光 / B. 善意 / C. 苹果 / D. 重新思考`。
- 截图：`pk-en-zh-retest-final.png`（1280×960，第 1/5 题，剩 18 秒，已答 0 题）。
- 作答后核对：选 C. 苹果，正确，150 分，作答行落库。

### 3.2 第 2 题（item 1，zh_en）— 防泄题通过

- 接口：`prompt_type=zh_en`，`headword=null`，`meaning_zh=香蕉`；未作答。
- 真机页面：题面 `香蕉`；选项 `A. disable / B. banana / C. writer / D. teacher`；题面未出现英文答案 `banana`。

### 3.3 其余题目接口契约复核（未逐题点击）

| 题号 | 题型 | 作答前 headword | meaning_zh | 契约 |
|---|---|---|---|---|
| 2 | en_zh | `careless` | 粗心的 | en_zh 透出，符合 |
| 3 | zh_en | `null` | 老师 | 不泄题，符合 |
| 4 | en_zh | `preheat` | 预热 | en_zh 透出，符合 |

## 4. 证据目录

| 文件 | 内容 |
|---|---|
| `../pk-en-zh-retest-final.png` | 真机第 1/5 题 en_zh：题面 `apple`，选项中文释义 |
| `http-evidence/pk-en-zh-retest-final-match.json` | 对局接口快照：各题 prompt_type / headword / meaning_zh / answered / is_correct |
| `http-evidence/pk-en-zh-retest-final-snapshot.json` | DB `snapshot_items` 原始快照 |
| 后端源码（容器） | `/app/backend/app/services/vocabulary_pk.py` `_item_view` headword 透出条件（en_zh 作答前透出，其余 null） |
| 前端源码 | `.qa-worktrees/qa-fixes/frontend/src/components/Vocabulary/Pk/PkArena.tsx` 题面/选项分流 |

## 5. 遗留风险项（保留记录，未清理 DB 锁证据）

上一轮复验期间（对局 `2e8e0187…`）后端曾整体超时（容器 unhealthy），DB 排查发现 PK 结算路径两条 `idle in transaction` 事务（pid 626930、626934）持有行/事务锁，阻塞 pid 626932 的 `UPDATE vocab_pk_player SET answered_count=…`，等待 3 分 08 秒；`idle_in_transaction_session_timeout=0`、`statement_timeout=0`。当时本地 `pg_terminate_backend` 终止两条空闲阻塞事务后后端恢复。

- 该现象与基线 D-S2（PK 超时结算计数/结算阈值）同属 `vocabulary_pk` 结算路径，**单列为最终风险项**：需核查结算事务是否存在未提交/未关闭的连接占用，建议补 `idle_in_transaction_session_timeout` 与事务边界审计。
- 本轮（对局 `f0c2e3ee…`）未再复现阻塞；相关历史记录保留在 `pk-en-zh-retest.md` §7，DB 锁证据未做清理。

## 6. 本次复验产生的本地测试数据（供清理）

| 类型 | 标识 | 终态 |
|---|---|---|
| PK 大厅 | `[id]` | closed |
| PK 对局 | `[id]` | active（未自然结算，按对局级联清理） |
| PK 玩家 | s10001 `7d48f349…` right active 150/answered 2/correct 1；s10002 `90e4f9ac…` left active 0/answered 1/correct 0 | 2 行 |
| PK 作答 | `[id]`（s10001）item 0 正确 150 | 1 行 |
| 其他 | 未新建/修改词库、词条、任务、课堂、账号；未写 `seedpilot-02`；临时 token 已从 `/tmp` 删除；浏览器已退出登录并清空 localStorage/sessionStorage，停留在登录页。 | — |
