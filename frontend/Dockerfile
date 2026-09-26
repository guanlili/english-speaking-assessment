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
# TLS 变体放 conf.d 之外（主配置 include conf.d/*.conf 全量加载，放里面会被
# 无条件生效，无证书时 nginx 起不来）；entrypoint 检测到证书时才替换进 conf.d
COPY ./frontend/nginx-tls.conf /etc/nginx/nginx-tls.conf
COPY ./frontend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 注意：声明 ENTRYPOINT 会重置基础镜像（nginx:1）继承的 CMD，必须显式补回
ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
