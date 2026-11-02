#! /usr/bin/env bash

set -e
set -x

# Let the DB start
python app/backend_pre_start.py

# Run migrations（admin 连接：受限角色无 DDL 权限）
alembic upgrade head

# 多租户 C4b：受限/平台角色幂等管理（Alembic 后跑——新表建完再授权；
# 凭据未配时自动跳过=不激活，开发/CI 形态零影响）
python scripts/ensure_db_roles.py

# Create initial data in DB（admin 连接绕 RLS 种子）
python app/initial_data.py
