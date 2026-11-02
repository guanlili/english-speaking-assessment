#!/usr/bin/env bash
# 多租户：接入一所新学校（D 期自助流程之前的种子工具）.
#
# 用法（生产服务器部署目录下）：
#   bash backend/scripts/onboard_tenant.sh <slug> <中文名> [管理员邮箱]
# 例：
#   bash backend/scripts/onboard_tenant.sh demo2 "示例第二中学" admin@demo2.edu.cn
#
# 幂等：租户存在则更新校名；管理员不存在才建（重跑不重置密码——
# 需要重置密码走后台改密或 SQL）。密码只打印一次。
# 之后的教师/学生账号由该校管理员走后台建号，全部自动落该校（写入侧
# 租户继承 + RLS 强制隔离，无需额外配置）。
# 设计依据 docs/multi-tenant-design.md §3/§4。

set -euo pipefail

SLUG="${1:?用法: onboard_tenant.sh <slug> <中文名> [管理员邮箱]}"
NAME_ZH="${2:?缺少学校中文名}"
ADMIN_EMAIL="${3:-admin@${SLUG}.edu.cn}"

# slug 规范：小写字母数字连字符（进 URL：/s/<slug>/login）
[[ "$SLUG" =~ ^[a-z0-9][a-z0-9-]{1,30}$ ]] || {
    echo "❌ slug 只能是小写字母/数字/连字符（2-31 位）"; exit 1; }

DB="docker compose -f compose.yml exec -T db"
BACKEND="docker compose -f compose.yml exec -T backend"

# 1) 租户（幂等 upsert：存在则改校名）
"$DB" psql -U postgres -d app -v slug="$SLUG" -v name="$NAME_ZH" <<'SQL'
INSERT INTO tenant (id, slug, name_zh, status, timezone, created_at)
VALUES (gen_random_uuid(), :'slug', :'name', 'active', 'Asia/Shanghai', now())
ON CONFLICT (slug) DO UPDATE SET name_zh = EXCLUDED.name_zh;
SQL

# 2) 管理员账号：不存在才建。哈希用后端容器内的同款实现（argon2）
EXISTS=$("$DB" psql -U postgres -d app -t -A -v slug="$SLUG" -v email="$ADMIN_EMAIL" <<'SQL'
SELECT 1 FROM "user" u, tenant t
WHERE u.tenant_id = t.id AND t.slug = :'slug' AND u.email = :'email';
SQL
)
if [[ "$EXISTS" == "1" ]]; then
    echo "ℹ️  管理员 $ADMIN_EMAIL 已存在，跳过建号（不重置密码）"
else
    PASSWORD=$(openssl rand -base64 18 | tr -d '/+=\n')
    HASH=$("$BACKEND" python -c \
        "import sys; from app.core.security import get_password_hash; print(get_password_hash(sys.argv[1]))" \
        "$PASSWORD")
    "$DB" psql -U postgres -d app -v slug="$SLUG" -v email="$ADMIN_EMAIL" -v hash="$HASH" <<'SQL'
WITH t AS (SELECT id FROM tenant WHERE slug = :'slug')
INSERT INTO "user" (id, email, hashed_password, role, is_active, tenant_id, created_at)
SELECT gen_random_uuid(), :'email', :'hash', 'school_admin', true, t.id, now() FROM t;
SQL
    echo "🔔 管理员初始密码: $PASSWORD   （仅本次打印，立即转交并提醒首登修改）"
fi

echo "✅ 学校就绪：$NAME_ZH（$SLUG）"
echo "   登录入口: https://outman.website/s/$SLUG/login"
echo "   管理员:   $ADMIN_EMAIL"
