#!/usr/bin/env bash
# 新项目初始化：一条命令完成改名 + 密钥随机化，替代手动照清单改 N 处。
#
# 用法（在新项目仓库根目录）：
#   bash scripts/init-project.sh "订单管理系统"
#   bash scripts/init-project.sh              # 不带参数则交互式输入
#
# 做的事：
#   1. 从 .env.example 生成 .env，随机化 SECRET_KEY / 数据库密码 / 管理员密码
#   2. PROJECT_NAME（.env）、APP_NAME（frontend/src/config.ts）、
#      页面标题（frontend/index.html）统一改为项目名
#   3. COMPOSE_PROJECT_NAME 根据项目名自动生成 slug，容器名随项目走
#   4. 输出剩余的手动待办清单

set -e
cd "$(dirname "$0")/.."

NAME="${1:-}"
if [ -z "$NAME" ]; then
  read -r -p "项目显示名（用于页面标题、邮件等，如：订单管理系统）: " NAME
fi
if [ -z "$NAME" ]; then
  echo "❌ 项目名不能为空" >&2
  exit 1
fi

if [ -f .env ]; then
  read -r -p ".env 已存在，覆盖并重新生成全部密钥？[y/N] " yn
  case "$yn" in
    [Yy]*) ;;
    *) echo "已取消，未做任何修改"; exit 1 ;;
  esac
fi

SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
ADMIN_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(12))")

cp .env.example .env

python3 - "$NAME" "$SECRET_KEY" "$DB_PASSWORD" "$ADMIN_PASSWORD" <<'EOF'
import pathlib
import re
import sys
import unicodedata

name, secret, db_pwd, admin_pwd = sys.argv[1:5]


def slugify(text: str) -> str:
    """把项目名转成适合做容器前缀的 slug：小写、字母数字、短横线。
    中文会被去掉（用 PROJECT_NAME 的中英文/数字部分），留英文和数字单词。
    """
    # 先把 Unicode 转成 ASCII（对带音标的拉丁字符有效，中文会变成空字符）
    normalized = unicodedata.normalize("NFKD", text)
    # 只保留字母、数字、空白和短横线
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", normalized)
    # 空白和连续短横线都换成单个短横线
    text = re.sub(r"[\s-]+", "-", text.strip().lower())
    text = text.strip("-")
    # 如果转出来是空的（比如全中文），fallback 到 my-project
    return text or "my-project"


def sub(path: str, pairs: list[tuple[str, str]]) -> None:
    p = pathlib.Path(path)
    s = p.read_text()
    for pattern, repl in pairs:
        # repl 用函数形式，避免项目名里的 \ 或 $ 被当作正则反向引用
        s, n = re.subn(pattern, lambda _m, r=repl: r, s, count=1, flags=re.M)
        if n != 1:
            sys.exit(f"❌ {path} 中未匹配到: {pattern}")
    p.write_text(s)


project_slug = slugify(name)

sub(".env", [
    (r"^PROJECT_NAME=.*$", f'PROJECT_NAME="{name}"'),
    (r"^COMPOSE_PROJECT_NAME=.*$", f"COMPOSE_PROJECT_NAME={project_slug}"),
    (r"^SECRET_KEY=.*$", f"SECRET_KEY={secret}"),
    (r"^POSTGRES_PASSWORD=.*$", f"POSTGRES_PASSWORD={db_pwd}"),
    (r"^FIRST_SUPERUSER_PASSWORD=.*$", f"FIRST_SUPERUSER_PASSWORD={admin_pwd}"),
])
sub("frontend/src/config.ts", [
    (r'export const APP_NAME = ".*"', f'export const APP_NAME = "{name}"'),
])
sub("frontend/index.html", [
    (r"<title>.*</title>", f"<title>{name}</title>"),
])
EOF

FIRST_SUPERUSER=$(grep '^FIRST_SUPERUSER=' .env | cut -d= -f2)
COMPOSE_PROJECT_NAME=$(grep '^COMPOSE_PROJECT_NAME=' .env | cut -d= -f2)

SLUG_WARNING=""
if [ "$COMPOSE_PROJECT_NAME" = "my-project" ]; then
  SLUG_WARNING="
⚠️  项目名是纯中文，容器前缀回退为 my-project。
    如果同一台机器上有多个项目，请手动修改 .env 里的 COMPOSE_PROJECT_NAME，
    否则容器名会冲突（比如 order-system / customer-mgmt 这种英文缩写）。"
fi

cat <<DONE
${SLUG_WARNING}

✅ 「${NAME}」初始化完成：
   - .env 已生成，SECRET_KEY / 数据库密码 / 管理员密码均为随机值
   - 前端 APP_NAME 和页面标题已改为「${NAME}」
   - 容器名前缀：${COMPOSE_PROJECT_NAME}（如 ${COMPOSE_PROJECT_NAME}-backend-1）

   本地管理员账号：${FIRST_SUPERUSER} / ${ADMIN_PASSWORD}（也记录在 .env）

📋 剩余手动待办：
   1. CLAUDE.md   —— 写入业务背景、数据模型、特殊约定（AI 开发的核心上下文）
   2. README.md   —— 改为项目自己的说明
   3. favicon     —— 替换 frontend/public/assets/images/favicon.png
   4. 首次启动    —— docker compose up --build
   5. 部署前      —— 按 README 配置 GitHub Secrets（SECRET_KEY 另生成新值，勿复用本地）
   6. 交付前      —— 删除 Items 示例代码（清单见 README「第四步」）
   7. 注册方式    —— 生产默认关闭自助注册（Secret USERS_OPEN_REGISTRATION 控制）；
                     "管理员建账号"模式的项目请一并删除注册页（见 README「第四步」）
DONE
