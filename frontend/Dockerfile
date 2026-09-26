# Stage base: 安装依赖（dev / build 共用）
# 注意：lockfile 需在仓库中提交（frontend/package-lock.json），npm ci 保证构建可复现
FROM node:24-slim AS base

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./

# 国内构建加速：npm 走 npmmirror
RUN npm config set registry https://registry.npmmirror.com

RUN --mount=type=cache,target=/root/.npm npm ci

COPY ./frontend ./

# Stage dev: 本地开发用 vite dev server（compose.override.yml 里 target: dev）
FROM base AS dev

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# Stage build: 编译静态文件
FROM base AS build-stage

ARG VITE_API_URL

RUN npm run build

# Stage final（默认 target）: nginx 托管静态文件 + 反代 /api
FROM nginx:1

COPY --from=build-stage /app/frontend/dist/ /usr/share/nginx/html

COPY ./frontend/nginx.conf /etc/nginx/conf.d/default.conf
# TLS 变体由 entrypoint 按证书存在与否选用（本地开发无证书，保持纯 HTTP）
COPY ./frontend/nginx-tls.conf /etc/nginx/conf.d/nginx-tls.conf
COPY ./frontend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
