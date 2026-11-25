# A. 平台运营授权只读台账 — QA 证据（2026-11-25）

对应 #517 第一块：平台运营登录后的只读授权台账页 `/admin/vocabulary-licenses`。
本目录为本地隔离环境取证，**未连接生产**，不含真实师生数据；样例词库均为 `[DEMO]` 本地合成数据。

## 环境口径

- 前端：worktree 源码 `vite` dev（`127.0.0.1:5199`，代理 `/api` 到本机后端）。
- 后端：worktree 源码 `uvicorn`（`127.0.0.1:8021`），连接本机开发库（Postgres `5433`，非测试库、非生产）。
- 浏览器：本机 Google Chrome（Playwright `channel: chrome`，设备模拟视口 + 触摸事件口径）。
- 截图为真实页面渲染（非静态 mock 图）；截图前已隐藏 devtools 浮标，并将侧栏账号邮箱替换为占位 `operator`。

## 截图矩阵（中文 / 英文 × 三档视口）

| 文件 | 语言 | 视口（宽×高） | 说明 |
|---|---|---|---|
| `zh-1180-license-ledger.png` | 中文 | 1180×820 桌面 | 统计卡、筛选区、台账表全量默认态 |
| `en-1180-license-ledger.png` | English | 1180×820 桌面 | 英文文案与状态/来源标签 |
| `zh-820-license-ledger.png` | 中文 | 820×1180 平板 | 侧栏 + 主区，表格内部横滚 |
| `en-820-license-ledger.png` | English | 820×1180 平板 | 英文平板档 |
| `zh-390-license-ledger.png` | 中文 | 390×844 手机 | 顶栏折叠、统计 2×2、筛选纵向堆叠、表格横滚提示 |
| `en-390-license-ledger.png` | English | 390×844 手机 | 英文手机档 |
| `zh-1180-credential-crop.png` | 中文 | 1180×820 桌面（表格横滚至右列） | 补充取证：到期日 / 凭证（含「授权书」http 链接）/ 备注·登记时间列可见 |

## 自动化与交互核验

- 前端：`npm run typecheck`、`npm run lint`（biome）、`npm test`（node:test + vitest，131 passed）通过。
- 后端：`bash scripts/verify.sh --openapi` 全闸门通过（格式 / ruff / ty / 全量测试 + 覆盖率门禁 / openapi 零漂移）。
- 浏览器交互核验（本机 dev stack）：
  - 状态筛选 `缺失` → 2 行，全部为「缺失」徽标；`临期` / `过期` / `有效` 口径同后端。
  - 学校筛选：无匹配显示空态；`演示学校` → 11 行；词库标题 `过期` → 1 行且均为「已过期」。
  - CSV 导出走既有平台 CSV 端点（平台 token，Blob 下载），文件名 `vocabulary-license-all-2026-11-25.csv`，表头首列为「学校」。
  - 凭证链接仅渲染 http/https，`rel="noopener noreferrer"`；不可信协议与空值显示 `–`。

## 响应式口径

- 三档视口页面级 `scrollWidth === clientWidth`，无横向溢出；宽表在卡片内部横滚（`overflow-x-auto`），窄屏有横滚提示。
- 本页筛选控件（输入框 / 下拉 / 导出按钮）高度 44px、输入字号 16px；侧栏与顶栏外壳按钮沿用全站既有尺寸（不在本页改动范围）。

## 未覆盖 / 说明

- 未做真机物理触摸测试；移动端结论来自 CDP/Chrome 设备模拟，真机缩放与软键盘顶起属 C 块范围。
- 台账为只读视图：页面无编辑 / 保存 / 删除授权入口；授权变更仍走既有学校侧与审计流。
