#!/usr/bin/env bash
# 在干净的 Linux 容器里重新生成 package-lock.json。
#
# 为什么需要这个脚本：npm 有个老 bug（https://github.com/npm/cli/issues/4828）——
# 在 macOS 上、node_modules 存在时生成的 lockfile 会丢失其他平台的原生依赖
# （@rolldown/binding-linux-* 等），导致 Docker 构建时报 "Cannot find native binding"。
# 解法：在没有 node_modules 干扰的 Linux 容器里生成，lock 会包含全平台依赖的超集，
# macOS / Linux / CI 通用。
#
# 何时执行：删除重建 lockfile、或 Docker 构建报原生绑定缺失时。日常 npm install 加包不需要。

set -e
cd "$(dirname "$0")/.."

# 匿名卷挂在 /w/node_modules 上，遮住宿主机的 node_modules，保证纯净解析
docker run --rm -v "$PWD":/w -v /w/node_modules -w /w node:20-slim \
  npm install --package-lock-only --ignore-scripts --no-audit --no-fund

echo "✅ package-lock.json 已重新生成，建议跟着跑一次："
echo "   rm -rf node_modules && npm ci   # 本地依赖与 lock 对齐"
