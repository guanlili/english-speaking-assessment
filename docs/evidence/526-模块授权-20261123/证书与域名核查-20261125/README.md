# 证书/TLS 与域名备案核查证据（2026-11-23）

本目录归档生产域名 `outman.website` 的证书切换后只读验证，以及域名 ICP 备案状态的官方查询记录。仅浏览器/`openssl`/`curl` 只读检查，不改 DNS、nginx、备案或生产配置，不触发部署。

## 目录

| 路径 | 内容 |
|---|---|
| `cert/README.md` | 证书修复验证说明：无拦截页、SAN、有效期、签发链、同源 API、CORS/mixed content、管理员登录与课堂页 |
| `cert/cert-domain.json` | 机读证据：证书 subject/issuer/SAN/有效期/链、HTTP 头、浏览器观察、限制 |
| `cert/B1-域名登录页.png` | 域名登录页首屏，无证书拦截 |
| `icp/README.md` | ICP 备案只读查询：`outman.website` 已备案、`test.zhiguan.online`/裸域无记录、`.website` 后缀可备案 |
| `icp/icp-query.json` | 机读证据：查询时间、官方来源、三条查询结果、后缀核查、第三方交叉与限制 |
| `icp/01,05-滑块校验` | 官方查询滑块过程截图 |
| `icp/02-官方-outman列表.png` | 官方列表：备案号 `京ICP备2022033467号-1`、审核日期 2022-11-25（主体姓名已打码） |
| `icp/03-官方-outman详情.png` | 官方详情：主体/服务信息、域名、前置审批项（主体姓名已打码） |
| `icp/04-官方-域名体系-WEBSITE.png` | 工信部域名体系英文 gTLD 列表含 `.WEBSITE` |
| `icp/06,07-暂无数据` | `test.zhiguan.online` 与裸域 `zhiguan.online` 均为 0 条 |

## 结论摘要

- `https://outman.website` 无证书拦截，`CN=outman.website`、SAN `DNS:outman.website`；自动续期后证书到期 `2027-02-21 10:54:14 GMT`。
- 前端 API 同源走相对 `/api`，无 CORS、mixed content、证书错误；管理员登录与课堂列表正常。
- `outman.website` 已在工信部备案（`京ICP备2022033467号-1`，2022-11-25，主体性质个人）；`zhiguan.online` 裸域及 `test.zhiguan.online` 暂无备案记录。
- `.website` 在工信部中国互联网域名体系英文 gTLD 列表内，属可提交备案后缀；后缀可备案不等于具体域名已备案。

## 安全与脱敏

- 服务器解析 IP、SSH 主机/生产 `.env` 路径、生产管理员账号来源均已替换为占位描述；用户名、密码、token 未入档。
- ICP 主体姓名已打码为「管**」，截图对应位置已遮盖；保留备案号、域名、审核日期与主体性质。
- **课堂页截图 B2/B3 未入库**：原图含真实教师姓名与班级名称，按隐私口径剔除；证书结论以 `cert-domain.json` 与登录页截图为准。
- 无真实学生信息、无 cookie/token、无生产内部地址。

## 体积与边界

- 约 1.9 MB、13 个文件；单文件最大 375 KB。
- 证书与备案均为查询时刻快照，后续可能续期/变更，正式决策以官方实时查询为准。
- 生产当前仍为 `51f4184`，本目录不涉及部署。
