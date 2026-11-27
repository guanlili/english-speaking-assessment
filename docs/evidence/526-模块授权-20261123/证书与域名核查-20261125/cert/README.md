# 证书修复验证 · 证据说明（2026-11-23）

## 背景

生产域名 `https://outman.website` 证书已切换为域名证书（任务前提：SAN=DNS:outman.website，到期 2027-02-17），nginx 已 reload、未重启容器。本轮做真实浏览器只读验证：确认无证书拦截、API 同源、无 CORS / mixed content / 证书错误，管理员可登录并正常进入课堂列表。

## 查询信息

- 查询时间：2026-11-23 19:21 (+08:00) / 11:21 UTC
- 目标：`https://outman.website/`（DNS 解析 `<服务器IP已脱敏>`）
- 方式：真实浏览器新开标签 + 本地 `openssl s_client` / `curl` 交叉校验；全程只读浏览
- 未做：未改生产 `.env`、未改 nginx、未改 DNS/备案、未重启容器、未登录云控制台；证据已归档、未改代码

## 结论

| 验证项 | 结果 | 依据 |
| --- | --- | --- |
| 证书拦截页 | 无。https 直接进入落地页 / 登录页，无证书风险提示 | 浏览器页面 `page_info` 为 `https://outman.website/login`；`cert-domain.json` → certificate.browser_interstitial |
| 证书主体 / SAN | `CN=outman.website`；SAN `DNS:outman.website` | openssl 握手链解析 |
| 证书有效期 | 2026-11-19 13:50:03 GMT ～ **2027-02-17 13:50:02 GMT** | openssl x509 dates |
| 签发链 | leaf → Let's Encrypt YE1 → ISRG Root YE → ISRG Root X2 → ISRG Root X1；对系统信任库 verify OK | openssl verify / `-showcerts` |
| HTTP 状态 | `HTTP/2 200`，nginx/1.31.9，HSTS `max-age=31536000`，X-Frame-Options DENY | `curl -I` |
| API 主机 | **同源相对 `/api`**，主机 `outman.website`；未观察到指向固定 IP 的绝对地址 API | 浏览器网络请求记录 |
| CORS 报错 | 无（同源，无需预检；控制台无 CORS 条目） | 控制台消息为空 |
| Mixed content | 无 `http://` 资源请求 | 网络请求记录 |
| 证书错误 | 无 | 控制台消息为空 |
| 管理员登录 | 成功，提交 `POST /api/v1/login/access-token` 200，跳转 `/classrooms` | 浏览器网络请求 + 页面跳转 |
| 课堂列表页 | 正常渲染，22 间课堂，侧边栏入口齐全，无失败 API | `cert-domain.json` → browser_observation.classrooms_page |

## 抓到的 API 请求（均 200，同源）

- `GET  /api/v1/login/options`（登录页）
- `POST /api/v1/login/access-token?remember=false`（提交登录）
- `GET  /api/v1/modules/me`
- `GET  /api/v1/exports`
- `GET  /api/v1/classes`
- `GET  /api/v1/users/me`

## 证据文件

| 文件 | 内容 |
| --- | --- |
| `B1-域名登录页.png` | 域名访问登录页首屏（教师/管理员表单，无证书拦截） |
| `B2-域名课堂页.png`（未入库） | 登录后 `/classrooms` 主内容区；因含真实教师姓名与班级名称，按隐私口径剔除 |
| `cert-domain.json` | 机读证据：证书 subject/issuer/SAN/有效期/链、页面 URL、API 主机、CORS/mixed content/证书错误、登录与课堂页状态、限制与脱敏说明 |

## 限制与口径

1. 浏览器页面 JS 无公开 API 读取 TLS 证书 subject/SAN/有效期；证书字段由本地 openssl 握手链解析，并用 curl 200 + 浏览器无拦截页交叉佐证。
2. 浏览器工具的网络/控制台缓冲在每次调用后排空，所列请求为本次会话内实际抓到的条目，不排除存在未被缓冲保留的早期请求。
3. 未在浏览器安全面板人工点开证书详情核对信任链；链完整性以 openssl verify 结果为准。
4. 生产管理员账号仅用于页面填写；用户名、密码、token 未打印到终端、未入档、未出现在截图与 JSON。

## 提交边界

本目录已作为独立证据归档；不改产品代码、不部署。

## 新域名证书复验（2026-11-23 20:29 +08:00 / 12:29 UTC）

自动续期切换到新证书后再次用真实浏览器打开 `https://outman.website/login`：浏览器直接落到已登录的 `/classrooms`，无证书拦截页、无警告；课堂页截图因含真实教师姓名/班级名称未入库，证书字段以文字与机读证据为准。新证书 `CN=outman.website`、SAN `DNS:outman.website`、到期 `2027-02-21 10:54:14 GMT`、SHA-256 指纹 `46:63:5B:40:4A:09:B4:C1:83:A8:E0:86:79:1F:C3:EA:F5:B0:F9:9F:CA:ED:E3:3E:B3:8F:33:1A:51:1B:6E:48`。`www.outman.website` 当前无 DNS 解析，未纳入 SAN。
