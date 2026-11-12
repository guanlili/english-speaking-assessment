# Stage base: 安装依赖（dev / build 共用）
# 注意：lockfile 需在仓库中提交（frontend/package-lock.json），npm ci 保证构建可复现
FROM node:24-slim AS base

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./

# 国内构建加速：npm 走 npmmirror
RUN npm config set registry https://registry.npmmirror.com

# 镜像源单包抽风时会连续卡在不同 tgz 上（实测 unplugin / shebang-regex 分别挂过一次，
# 整站不可达时连 registry.npmmirror.com 首页都超时），只 rerun 靠运气不划算。
# 两个层次兜：先把单包下载超时放宽并加满重试，仍未成就整条换官方源重来一遍。
# 不改依赖版本、不改 lockfile；构建成功路径上多出的只有这些 fetch 参数。
ARG NPM_FETCH="--fetch-retries=5 --fetch-retry-mintimeout=20000 --fetch-retry-maxtimeout=180000 --fetch-timeout=180000"
RUN --mount=type=cache,target=/root/.npm \
    npm ci $NPM_FETCH \
 || (npm config set registry https://registry.npmjs.org && npm ci $NPM_FETCH)

COPY ./frontend ./

# Stage dev: 本地开发用 vite dev server（compose.override.yml 里 target: dev）
FROM base AS dev

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# Stage build: 编译静态文件
FROM base AS build-stage

ARG VITE_API_URL
# 前端 Sentry DSN（可选；为空时 Sentry.init 不执行，产物不含上报逻辑的配置）
ARG VITE_SENTRY_DSN

RUN npm run build

# Stage final（默认 target）: nginx 托管静态文件 + 反代 /api
FROM nginx:1

COPY --from=build-stage /app/frontend/dist/ /usr/share/nginx/html
# 服务器侧 checkout 的 umask 是 077，public/ 下的静态文件会以 600 保留进 dist，
# nginx worker（非 root）读不到就是 403 —— 实测 robots.txt / sitemap.xml 上线即 403。
# vite 自己生成的 index.html、assets 是 644 所以没暴露；这里统一放宽读权限兜住。
RUN chmod -R a+rX /usr/share/nginx/html

COPY ./frontend/nginx.conf /etc/nginx/conf.d/default.conf
# TLS 变体放 conf.d 之外（主配置 include conf.d/*.conf 全量加载，放里面会被
# 无条件生效，无证书时 nginx 起不来）；entrypoint 检测到证书时才替换进 conf.d
COPY ./frontend/nginx-tls.conf /etc/nginx/nginx-tls.conf
COPY ./nginx-extra/outman.press.conf /etc/nginx/outman.press.conf
COPY ./frontend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 注意：声明 ENTRYPOINT 会重置基础镜像（nginx:1）继承的 CMD，必须显式补回
ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
