# nginx-extra · 同机附加 vhost

SpeakUp `frontend` 容器内的 nginx 除主站 `default.conf` / `nginx-tls.conf` 外，还可按需启用额外域名。当前仅 **outman.press**（遇己 yujee，反代宿主机 `:8080`）。

## outman.press 启用条件

| 项 | 路径 |
| --- | --- |
| 配置模板（镜像内） | `/etc/nginx/outman.press.conf`（来自本目录 `outman.press.conf`） |
| 运行时启用 | entrypoint 在 **证书齐全** 时 `cp` 到 `/etc/nginx/conf.d/outman.press.conf` |
| 证书（宿主机 → 容器只读） | `./ssl/outman.press/fullchain.pem` + `./ssl/outman.press/privkey.pem` |

无证书时 **不会** 写入 `conf.d`，SpeakUp nginx 照常启动；遇己 HTTPS 不对外。

## DevOps：首次启用或变更前

1. **备份**（改前必做）：容器内或宿主机保留一份 `conf.d/` 清单、`nginx-tls.conf`、`outman.press.conf` 副本，以及 `./ssl/` 目录列表；记录 `docker compose ps` 与 SpeakUp 主域名冒烟结果。
2. **证书**：签发/续期到 `./ssl/outman.press/`（与 SpeakUp 主站 `./ssl/fullchain.pem` **隔离**）；推荐沿用 compose 内 acme.sh DNS-01（DNSPod），与主站相同流程、不同域名目录。
3. **部署**：merge 后 CI 部署会重建 `frontend` 镜像；仅证书变更时可 `docker compose up -d --build frontend`（或等 pipeline），entrypoint 会自动检测证书并挂 conf。
4. **校验**：在 frontend 容器内执行 `nginx -t`，再 `docker compose exec frontend nginx -s reload`（若 entrypoint 已 reload 可跳过）。
5. **双站冒烟**（验收 A2 / A5）：
   - `curl -sI http://outman.press/` → `301`/`308`，`Location: https://outman.press/...`（**不得** 500；`:80` 仅 `return`，不 `proxy_pass`）
   - `curl -sI http://www.outman.press/` → 同上，统一到 apex HTTPS
   - `curl -sI https://outman.press/` → 200，落到遇己（当前为 `/zh` 等应用路由）
   - SpeakUp **原域名**：HTTPS 首页、登录、上传/API、证书有效期

## 回滚

| 方式 | 操作 |
| --- | --- |
| 关闭遇己 vhost | 移走或重命名 `./ssl/outman.press/` 下证书 → 重建/重启 `frontend` → entrypoint 不再复制 conf |
| 或 | 删除容器内 `/etc/nginx/conf.d/outman.press.conf` 并 reload（下次重启会被 entrypoint 再次写入，除非证书已移走） |
| SpeakUp | 主站 `default.conf` / 主证书 **勿删**；回滚后原域名应立刻恢复 |

业务代码与 SpeakUp API **不在此目录变更**；遇己应用 env（`WEB_BASE_URL` 等）见 yujee-china 仓库与 [SA · outman.press 备案与 HTTPS](https://app.notion.com/p/4079aef5c210818bab61dae159587ef0)。
