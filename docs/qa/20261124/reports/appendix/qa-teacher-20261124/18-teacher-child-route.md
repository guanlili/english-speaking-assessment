# 18 · 教师子路由 speaking 守卫复验

- 复验时间：2026-11-24（Asia/Shanghai）；分支 `fix/qa-vocab-regression-20261124`（PR #543）
- 浏览器：**独立 Playwright 无头上下文**（chromium headless shell 1148），未占用共享 Chrome / 5175
- 被测路由：`/t/$code/s/$studentId`（学生学习档案 / 进步轨迹页），源码 `frontend/src/routes/t.$code.s.$studentId.tsx`

## 守卫口径

- 路由用 `moduleGuardState({ isPending, isError }, hasModule, "speaking")` 判定；key 为 **`speaking`**（不是 vocabulary）。
- `loading` → 骨架屏；`denied` → 渲染 `<ModuleDeniedPanel module="speaking" />`（文案「本校暂未开通口语模块。」/ "The speaking module is not enabled for this school."）；`allowed` → 放行并发 `readStudentTrail` / `readClassBoard` 请求。
- 模块清单：`GET /api/v1/modules/me`；服务端闸门仍是最终裁决，前端拦截只减少无效直达。

## 结论：通过

| 租户 | 模块开通（modules/me） | 被测子路由 | 落点 | 接口 | 判定 |
|---|---|---|---|---|---|
| seedpilot-01 | `["speaking", "vocabulary"]` | `/t/SD100X/s/[id]`（学生1-1） | 正常渲染学生档案页，无拦截面板 | board **200**，trail **200** | **通过：已购 speaking 不误拦** |
| seedpilot-02 | `["speaking"]`（**vocabulary 关闭**） | `/t/SD200X/s/[id]`（学生1-2，课堂 SD200X） | 正常渲染学生档案页，无拦截面板 | modules/me **200**，board **200**，trail **200** | **通过：vocabulary 关闭不影响 speaking 子路由** |

## 一、seedpilot-01（speaking + vocabulary 均已购）

- 教师账号：`[本地测试账号]`；学生 s10001（学生1-1，id `[id]`）。
- 直连 `/t/SD100X/s/7d48f349-…`：未出现「本校暂未开通口语模块」/ "speaking module is not enabled" 文案（zh/en 计数均为 0）。
- 页面正常渲染：页头「学生学习档案 · 学生1-1 · 课堂 SD100X · 进步轨迹与历史反馈」；每次练习表 2026-11-17 参考分 73.5 / 跟读完整度 96 / 作答 4；阶段学习报告与历史练习反馈均在。
- 截图（zh/en × 390/1180 各一张）：
  - `18-guard-zh-1180.png`（中文 · 桌面 1180）
  - `18-guard-zh-390.png`（中文 · 移动 390）
  - `18-guard-en-1180.png`（英文 · 桌面 1180）
  - `18-guard-en-390.png`（英文 · 移动 390）
- 两宽度下页面均正常排版：桌面侧栏展开、卡片单列；移动 390 侧栏收起、卡片纵向堆叠，无守卫拦截、无报错空态。

## 二、seedpilot-02（speaking 已购 / vocabulary 关闭）

- 教师账号：`[本地测试账号]`（UI 真实登录，密码同 `[本地测试口令已移除]`）；课堂 `SD200X`「试点班 2-1」；学生 学生1-2，id `[id]`。
- `modules/me` 返回 `{"modules":["speaking"]}`（vocabulary 不在清单内；DB `tenant_module`：speaking=t、vocabulary=f）。
- 直连 `/t/SD200X/s/58699914-…`：未出现 speaking 拦截面板，也未出现 vocabulary 拦截文案；页面正常渲染「学生学习档案 · 学生1-2 · 课堂 SD200X」，轨迹表 2026-11-17 参考分 76 / 完整度 77 / 作答 4，历史反馈 4/4 · 81.2。
- 截图：`18-seed02-child-route.png`。
- 实际落点 URL：`http://本地服务/t/SD200X/s/[id]`（未被重定向到拦截页或课堂列表）。

## 三、接口与清单留证

- `scratch/modules-me-seed001.json`：`{"modules":["speaking","vocabulary"]}`
- `scratch/modules-me-seed002.json`：`{"modules":["speaking"]}`
- DB 对照（`tenant_module`）：seedpilot-01 speaking=t / vocabulary=t；seedpilot-02 speaking=t / vocabulary=f。

## 四、说明

- 本路由守卫 key 为 `speaking`，与词汇模块开关解耦：vocabulary 关闭的学校只要 speaking 已购，教师仍可打开学生档案/轨迹页；反之未购 speaking 才会落到 `ModuleDeniedPanel`。
- 前端守卫仅做入口过滤，服务端 `readStudentTrail` / `readClassBoard` 闸门仍是最终裁决；本轮两租户接口均 200，未触发 403。
