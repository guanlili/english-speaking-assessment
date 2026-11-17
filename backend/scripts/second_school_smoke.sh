#!/usr/bin/env bash
# 第二校上线冒烟：学校入口 → 管理员 → 教师 → 课堂 → 同号学生 → 跨校越权
#
# 用法（在部署目录或本地仓库根跑）：
#   SECOND_SCHOOL_API=https://<域名>/api/v1 \
#   B_SLUG=bj-2zhong B_ADMIN=admin@bj-2zhong.edu.cn B_ADMIN_PWD='<初始密码>' \
#   A_SLUG=seedpilot-01 A_STU=s10001 A_STU_PWD='<A校学生密码>' \
#   bash backend/scripts/second_school_smoke.sh
#
# 覆盖 V1.0 验收里可在接口层自动化的部分（AC-01/02/03 + 学校入口解析）；
# 录音回放、恢复演练、混合负载这些需要人工或专项脚本，不在这里做。
# 幂等：重复执行会复用已建的教师/课堂/学生，只在缺的时候补建。
#
# 注意（bash 3.2 实测）：变量名紧跟中文会被并进变量名，一律写 ${VAR}；
# JSON 请求体先拼进变量再传，不在 $( ) 里嵌套引号（花括号会被展开）。
set -uo pipefail

API=${SECOND_SCHOOL_API:-http://127.0.0.1:8000/api/v1}
B_SLUG=${B_SLUG:?需提供 B_SLUG（第二校 slug）}
B_ADMIN=${B_ADMIN:?需提供 B_ADMIN（第二校管理员邮箱）}
B_ADMIN_PWD=${B_ADMIN_PWD:?需提供 B_ADMIN_PWD}
A_SLUG=${A_SLUG:-seedpilot-01}
A_STU=${A_STU:-}
A_STU_PWD=${A_STU_PWD:-}
B_TEACHER=${B_TEACHER:-t01@${B_SLUG}.example}
B_TEACHER_PWD=${B_TEACHER_PWD:-Teach2026!x}
DB_CONTAINER=${DB_CONTAINER:-english-speaking-assessment-db-1}
DB_NAME=${DB_NAME:-app}

pass=0; fail=0
ok(){ echo "  ✅ $1"; pass=$((pass+1)); }
no(){ echo "  ❌ $1"; fail=$((fail+1)); }
chk(){ [ "$2" = "$3" ] && ok "$1（$2）" || no "$1（期望 $3，实际 $2）"; }
field(){ python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('$1',''))" 2>/dev/null; }
token(){ python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('access_token',''))" 2>/dev/null; }
sql(){ docker exec "$DB_CONTAINER" psql -U postgres -d "$DB_NAME" -tAc "$1" 2>/dev/null | tr -d '\r'; }
login(){ # login <slug> <username> <password>
  local form
  form=$(printf 'username=%s&password=%s' "$2" "$3")
  curl -s -X POST "$API/login/access-token?school=$1" \
    -H 'Content-Type: application/x-www-form-urlencoded' --data "$form" | token
}

echo "== 0. 学校入口解析 =="
chk "已知 slug 返回 200" "$(curl -s -o /tmp/ss_school.json -w '%{http_code}' "$API/login/school/$B_SLUG")" "200"
SNAME=$(field name_zh < /tmp/ss_school.json)
[ -n "$SNAME" ] && ok "校名解析为「${SNAME}」" || no "校名为空"
chk "未知 slug 统一 404" "$(curl -s -o /dev/null -w '%{http_code}' "$API/login/school/no-such-school")" "404"

echo "== 1. 第二校管理员登录 =="
TOK_B=$(login "$B_SLUG" "$B_ADMIN" "$B_ADMIN_PWD")
[ -n "$TOK_B" ] && ok "管理员登录成功" || { no "管理员登录失败"; echo "== 中止：拿不到管理员 token =="; exit 1; }
chk "角色为 school_admin" "$(curl -s "$API/users/me" -H "Authorization: Bearer ${TOK_B}" | field role)" "school_admin"

echo "== 2. 建教师（幂等） =="
MEMBER_BODY=$(printf '{"email":"%s","full_name":"冒烟教师","password":"%s"}' "$B_TEACHER" "$B_TEACHER_PWD")
TC=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/school/members" \
  -H "Authorization: Bearer ${TOK_B}" -H 'Content-Type: application/json' -d "$MEMBER_BODY")
case "$TC" in
  200|201) ok "教师新建成功（HTTP ${TC}）";;
  400)     ok "教师已存在（HTTP 400），直接复用";;
  *)       no "建教师失败（HTTP ${TC}）";; esac

echo "== 3. 教师登录并取名下课 =="
TOK_T=$(login "$B_SLUG" "$B_TEACHER" "$B_TEACHER_PWD")
[ -n "$TOK_T" ] && ok "教师登录成功" || { no "教师登录失败"; exit 1; }
code_of(){ python3 -c "import sys,json;d=json.load(sys.stdin);print(d[0]['code'] if d else '')" 2>/dev/null; }
id_of(){ python3 -c "import sys,json;d=json.load(sys.stdin);print(d[0]['id'] if d else '')" 2>/dev/null; }
CLS_LIST=$(curl -s "$API/classes" -H "Authorization: Bearer ${TOK_T}")
CLS_B=$(echo "$CLS_LIST" | id_of)
CODE_B=$(echo "$CLS_LIST" | code_of)
if [ -z "$CLS_B" ]; then
  NEW_BODY='{"name":"冒烟课堂","class_size":60}'
  CLS_B=$(curl -s -X POST "$API/classes" -H "Authorization: Bearer ${TOK_T}" \
    -H 'Content-Type: application/json' -d "$NEW_BODY" | field id)
  [ -n "$CLS_B" ] && ok "课堂已新建" || { no "建课堂失败"; exit 1; }
  CODE_B=$(curl -s "$API/classes" -H "Authorization: Bearer ${TOK_T}" | code_of)
else
  ok "复用已有课堂 ${CODE_B}"
fi

echo "== 4. 导入本校学生（与 A 校同号） =="
if [ -n "$A_STU" ]; then
  IMP_BODY=$(printf '{"classroom_id":"%s","lines":[{"username":"%s","full_name":"冒烟学生"}]}' "$CLS_B" "$A_STU")
  IMP_RES=$(curl -s -X POST "$API/students/import" -H "Authorization: Bearer ${TOK_T}" \
    -H 'Content-Type: application/json' -d "$IMP_BODY")
  IMP_ST=$(echo "$IMP_RES" | python3 -c "import sys,json;print(json.load(sys.stdin)['rows'][0]['status'] or 'error')" 2>/dev/null)
  case "$IMP_ST" in
    created|joined_existing|already_enrolled) ok "同号学生就绪：${IMP_ST}";;
    error)
      if echo "$IMP_RES" | grep -q "姓名与已有账号不一致"; then
        ok "同号学生已存在（姓名不同，属幂等复用）"
      else
        no "导入失败：$(echo "$IMP_RES" | head -c 160)"
      fi;;
    *)     ok "导入结果：${IMP_ST}";; esac
fi

echo "== 5. AC-01 同号双校各自登录 =="
TOK_SB=$(login "$B_SLUG" "$A_STU" "brs123456")
[ -n "$TOK_SB" ] && ok "B 校学生登录成功" || no "B 校学生登录失败"
if [ -n "$A_STU_PWD" ]; then
  TOK_SA=$(login "$A_SLUG" "$A_STU" "$A_STU_PWD")
  [ -n "$TOK_SA" ] && ok "A 校同号学生登录成功" || no "A 校同号学生登录失败"
  if [ -n "$TOK_SA" ] && [ -n "$TOK_SB" ]; then
    IDA=$(curl -s "$API/users/me" -H "Authorization: Bearer ${TOK_SA}" | field id)
    IDB=$(curl -s "$API/users/me" -H "Authorization: Bearer ${TOK_SB}" | field id)
    [ "$IDA" != "$IDB" ] && ok "同号在两校是独立账号" || no "同号指向同一账号"
  fi
fi

echo "== 6. 错校登录不泄露（同一文案） =="
FORM_T=$(printf 'username=%s&password=%s' "$B_TEACHER" "$B_TEACHER_PWD")
FORM_BAD=$(printf 'username=%s&password=wrong' "$B_TEACHER")
WRONG_SCHOOL=$(curl -s -o /tmp/ss_e1.json -w '%{http_code}' -X POST "$API/login/access-token?school=$A_SLUG" \
  -H 'Content-Type: application/x-www-form-urlencoded' --data "$FORM_T")
WRONG_PWD=$(curl -s -o /tmp/ss_e2.json -w '%{http_code}' -X POST "$API/login/access-token?school=$B_SLUG" \
  -H 'Content-Type: application/x-www-form-urlencoded' --data "$FORM_BAD")
chk "B 校教师从 A 校入口登录被拒" "$WRONG_SCHOOL" "400"
chk "B 校教师密码错误被拒" "$WRONG_PWD" "400"
D1=$(field detail < /tmp/ss_e1.json); D2=$(field detail < /tmp/ss_e2.json)
[ "$D1" = "$D2" ] && ok "错校/错密码文案一致" || no "文案不同：[$D1] vs [$D2]"

echo "== 7. AC-02/03 跨校不可见 =="
A_CODES=$(sql "select c.code from classroom c join tenant t on t.id=c.tenant_id where t.slug='$A_SLUG'")
BCODES=$(curl -s "$API/classes" -H "Authorization: Bearer ${TOK_T}" | python3 -c "import sys,json;print(' '.join(c['code'] for c in json.load(sys.stdin)))" 2>/dev/null)
LEAK=0
for c in $BCODES; do case " $A_CODES " in *" $c "*) LEAK=1;; esac; done
[ "$LEAK" = "0" ] && ok "教师课堂列表未见 A 校课堂码（本校：${BCODES}）" || no "列表出现 A 校课堂码"
A_CODE1=$(echo "$A_CODES" | head -1)
if [ -n "$A_CODE1" ]; then
  BOARD=$(curl -s -o /dev/null -w '%{http_code}' "$API/classes/$A_CODE1/board" -H "Authorization: Bearer ${TOK_T}")
  chk "B 校教师读 A 校课堂面板（${A_CODE1}）被拒" "$BOARD" "404"
  JOIN=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/classes/$A_CODE1/join" \
    -H "Authorization: Bearer ${TOK_SB}" -H 'Content-Type: application/json' -d '{}')
  chk "B 校学生用 A 校课堂码入班被拒" "$JOIN" "404"
else
  no "取 A 校课堂码失败（检查 DB_CONTAINER / DB_NAME）"
fi

echo "== 8. AC-03 篡改 classroom_id 越权 =="
A_CLS_ID=$(sql "select c.id from classroom c join tenant t on t.id=c.tenant_id where t.slug='$A_SLUG' limit 1")
CROSS_BODY=$(printf '{"classroom_id":"%s","lines":[{"username":"cross_school_probe","full_name":"越权探针"}]}' "$A_CLS_ID")
CROSS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/students/import" \
  -H "Authorization: Bearer ${TOK_T}" -H 'Content-Type: application/json' -d "$CROSS_BODY")
chk "B 校教师向 A 校 classroom_id 导学生被拒" "$CROSS" "404"

echo
echo "== 汇总：${pass} 通过 / ${fail} 失败 =="
exit $([ "$fail" -eq 0 ] && echo 0 || echo 1)
