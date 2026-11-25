# D-S3 修复真机复验记录 · 2026-11-24

## 1. 结论

**真机复验：未通过（端到端缺口）**；前端组件回归测试通过，但 5176 真实页面上 en_zh 题面在作答前仍显示中文释义，未显示英文 headword。

| 层面 | 结果 | 说明 |
|---|---|---|
| 修复分支源码 | 已确认 | 5176 Vite 工作树 `.qa-worktrees/qa-fixes`，分支 `fix/qa-vocab-regression-20261124`，commit `4c9bd4b`「fix(pk): en_zh 题面按题型展示英文 headword」 |
| 前端分流代码 | 已下发 | 5176 实际下发的 `PkArena.tsx` L576：`prompt_type === "en_zh" && currentItem.headword ? currentItem.headword : currentItem.meaning_zh`；选项侧 L616 方向正确 |
| 组件回归单测 | 通过（PR 自述 3/3） | `tests/components/PkArena.test.tsx` 用例 mock 了 `headword: "apple"`，断言题面含 apple、不含「苹果」 |
| 真机 en_zh 题面 | **未通过** | 作答前接口 `headword=null`，前端回退 `meaning_zh`，页面题面仍为中文；两道 en_zh 题均复现 |
| 对照 zh_en 题面 | 通过 | 题面中文释义、选项英文单词，方向正确 |

> 判定口径：任务要求「进入对局后找到 en_zh 题，截图并断言题面是英文 headword（不是中文 meaning_zh），选项仍为中文释义」。真机题面为中文释义，断言不成立，记未通过。

## 2. 环境与账号（本地隔离）

- 前端：`http://本地服务`（修复分支 Vite，未触碰 5175）；后端 `http://本地服务`；DB `app`。
- 租户 `seedpilot-01`，课堂 `SD100X`；词库 `[id]`（18 词）。
- 教师 `[本地测试账号]`（API 开/关大厅）；学生 s10001（浏览器真实点击）、s10002（API 入队配对）。统一密码 `[本地测试口令已移除]`（本地测试账号）。
- 本次新增大厅 `[id]`（5 题，30 秒/题，题型 en_zh + zh_en）；对局 `[id]`。测完大厅已关闭。

## 3. 复现步骤

1. 教师 API 开厅（目标 18 词书，5 题，30s/题，`prompt_types=[en_zh, zh_en]`）。
2. 浏览器打开 `http://本地服务/s/seedpilot-01/login`，清存储后登录 s10001，进入 `/vocab/SD100X/pk` 点击「加入 PK」。
3. s10002 API 入队，自动配对进入对局。
4. 读取真实页面 `[data-testid=pk-prompt]` 题面与选项文本；对照接口快照字段。

## 4. 真机观测记录

### 4.1 第 1 题（item 0，en_zh）— 题面方向错误

- 接口：`prompt_type=en_zh`，`meaning_zh=苹果`，作答前 `headword=null`；DB 快照目标词 `headword=apple`。
- 真机页面：**题面「苹果」**；选项 `A. 阳光 / B. 善意 / C. 苹果 / D. 重新思考`（选项为中文释义，正确）。
- 期望：题面英文 `apple`，选项中文释义。
- 截图：`pk-en-zh-retest.png`（1280×960，第 1/5 题，剩 29 秒）。

### 4.2 第 2 题（item 1，zh_en）— 对照，方向正确

- 接口：`prompt_type=zh_en`，`meaning_zh=香蕉`。
- 真机页面：题面「香蕉」；选项 `A. disable / B. banana / C. writer / D. teacher`（选项英文单词，正确）。

### 4.3 第 3 题（item 2，en_zh）— 再次复现

- 接口：`prompt_type=en_zh`，`meaning_zh=粗心的`，作答前 `headword=null`；DB 快照目标词 `headword=careless`。
- 真机页面：**题面「粗心的」**；选项 `A. 向日葵 / B. 粗心的 / C. 香蕉 / D. 爆米花`。

### 4.4 作答后字段变化（佐证根因）

- s10001 作答 item 0（选 apple，正确，150 分）、item 1（选 banana，正确，110 分）后，接口中这两题 `headword` 才被透出（`apple` / `banana`）；未作答题 `headword` 仍为 `null`。
- 作答与判分、速度加成落库正常：2 条作答行，正确 2，总分 260。

## 5. 根因定位

- **前端（已修复）**：`PkArena.tsx` 题面按题型分流，en_zh 读 `currentItem.headword`，zh_en 读 `meaning_zh`。分流逻辑本身正确，5176 下发包已含该分支。
- **后端（缺口）**：`backend/app/services/vocabulary_pk.py` `_item_view`（L829–839）构造 `PkMatchItem` 时，`headword=str(snapshot_typed["headword"]) if answer is not None else None`——**仅在本题已有作答记录时才透出目标词 headword**；作答前一律 `null`。
- 对局快照 `snapshot_items` 中目标词 headword 是完整存在的（apple / banana / careless / teacher / preheat），但视图层作答前未把它放进接口返回。
- 因此前端 `currentItem.headword` 为 `null`，条件 `en_zh && headword` 不成立，回退渲染 `meaning_zh`，en_zh 题面仍是中文。
- 单测之所以通过：`PkArena.test.tsx` L108–119 的 mock 数据直接给了 `headword: "apple"`，未覆盖「后端作答前返回 headword=null」的真实契约。

## 6. 修复建议

1. **后端补透出（主修复点）**：`_item_view` 对选择题型（en_zh / zh_en）在作答前也从 `snapshot_typed` 透出目标词 `headword`（必要时一并透出 `word_id`），不要依赖 `answer is not None`；已作答题保持现状即可。
2. **前端回归补一条契约用例**：mock `headword=null`、`prompt_type=en_zh` 时的降级表现明确化，避免后续把「后端未透出」误判为前端渲染问题。
3. 前端分流代码本次无需再改；待后端透出后真机复核 en_zh 题面为英文 headword。

## 7. 附带观察：后端 DB 阻塞事务（环境事件，非本次判定项）

复验开赛后后端一度整体超时（容器 unhealthy，主机与容器内访问 8000 均 6s+ 超时）。DB 排查发现 PK 结算路径上两条 `idle in transaction` 事务（pid 626930、626934）持有行/事务锁，阻塞 pid 626932 的 `UPDATE vocab_pk_player SET answered_count=…`（等待 3 分 08 秒，`idle_in_transaction_session_timeout=0`、`statement_timeout=0`）。本地处置：`pg_terminate_backend` 终止两条空闲阻塞事务后后端恢复（200，10–20ms）。

- 关联：与基线报告 D-S2（PK 超时结算计数/结算阈值）同属 `vocabulary_pk` 结算路径，建议一并核查结算事务是否存在未提交/未关闭的连接占用；本记录仅作环境事件留痕，未改动代码。

## 8. 证据目录

| 文件 | 内容 |
|---|---|
| `../pk-en-zh-retest.png` | 真机第 1/5 题 en_zh：题面「苹果」，选项中文释义 |
| `http-evidence/pk-en-zh-retest-match.json` | 对局接口快照：各题 prompt_type / headword / meaning_zh / answered / is_correct |
| `http-evidence/pk-en-zh-retest-snapshot.json` | DB `snapshot_items` 原始快照：目标词 headword 完整存在 |
| 前端源码 | `.qa-worktrees/qa-fixes/frontend/src/components/Vocabulary/Pk/PkArena.tsx` L380–382（题面分流）、L404–406（选项分流） |
| 后端源码 | `backend/app/services/vocabulary_pk.py` L829–839（`_item_view` headword 透出条件） |
| 单测 | `.qa-worktrees/qa-fixes/frontend/tests/components/PkArena.test.tsx` L105–133（mock headword 用例） |

## 9. 本次复验产生的本地测试数据（供清理）

| 类型 | 标识 | 终态 |
|---|---|---|
| PK 大厅 | `[id]` | closed |
| PK 对局 | `[id]` | active（未自然结算，清理时按对局级联） |
| PK 玩家 | s10001 `7d48f349…` right active 260/answered 3/correct 2；s10002 `90e4f9ac…` left active 0/answered 1/correct 0 | 2 行 |
| PK 作答 | `63f10638…`（s10001）item 0 正确 150、item 1 正确 110 | 2 行 |
| 其他 | 未新建/修改词库、词条、任务、课堂、账号；未写 `seedpilot-02`；临时 token 已从 `/tmp` 删除；浏览器已退出登录并清空 localStorage/sessionStorage，停留在登录页。 | — |
