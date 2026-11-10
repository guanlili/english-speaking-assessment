#!/usr/bin/env bash

set -e
set -x

# --reruns：全套共享测试库存在低概率的顺序/时序漂移失败（受害者随机，
# 单测隔离跑恒绿）。真实回归会连续失败两次仍然红；重跑只吸收漂移噪声，
# 不吞确定性问题。重跑的用例会在输出里标 RERUN，可追溯。
coverage run -m pytest tests/ --reruns 2 --reruns-delay 2

# ── 覆盖率门禁 ──────────────────────────────────────────────────────────
# 全局：当前实测 93%（约 15869 语句 / 1163 miss），取 92 留一个点的缓冲。
# 它防的是「某一批改动顺手带进大片未覆盖代码」——纯重构不该让它掉，
# 掉了就说明有分支没被任何用例走到。
coverage report --fail-under=92

# 分层：`coverage report` 多个 --include 只有最后一个生效，所以按目录分别跑。
# 阈值取各自实测值向下取整，留 1-2 点缓冲：
#   services 93% / scoring 93% / api 92% / core 91%
# 分层是为了防「总量达标、某个模块悄悄烂掉」——全局 92% 掩盖不了一个
# 60% 的 scoring 模块，分目录跑就会当场红。
coverage report --include="app/services/*" --fail-under=92
coverage report --include="app/scoring/*" --fail-under=92
coverage report --include="app/api/*" --fail-under=91
coverage report --include="app/core/*" --fail-under=90

# CI 里把覆盖率摘要贴到 job summary，PR 页面直接能看到，不用点进日志翻。
if [ -n "$GITHUB_STEP_SUMMARY" ]; then
  {
    echo "## 后端覆盖率"
    echo
    coverage report --format=markdown --skip-covered
  } >> "$GITHUB_STEP_SUMMARY"
fi

coverage html --title "${@-coverage}"
