import { type APIRequestContext, expect, test } from "@playwright/test"

/**
 * 整校模块授权（#517）端到端场景：只口语 / 只单词两校对照（integration，真实后端，local 环境）。
 *
 * 链路：平台运营开两校 → 各校建教师 → 运营后台改写模块开关 → 教师拉 /modules/me 核对清单 →
 * 审计历史留痕。403/404 成员优先级矩阵由后端测试 test_module_entitlement.py 全覆盖；
 * 本 spec 只锁跨校口径与下发契约，不依赖课堂成员与种子数据。
 *
 * 数据自造自清（slug 带时间戳唯一）。需本地后端已合入本分支代码与迁移。
 */

const suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`

interface SchoolFixture {
  tenantId: string
  slug: string
  token: string
}

async function createSchoolWithTeacher(
  request: APIRequestContext,
  opToken: string,
  label: string,
): Promise<SchoolFixture> {
  const slug = `e2e-mod-${label}-${suffix}`.slice(0, 31)
  const tenantResp = await request.post("/api/v1/admin/tenants", {
    headers: { Authorization: `Bearer ${opToken}` },
    data: { slug, name_zh: `E2E模块-${label}` },
  })
  expect(tenantResp.ok(), await tenantResp.text()).toBeTruthy()
  const tenant = (await tenantResp.json()) as { id: string }

  const email = `mod-${slug}@example.com`
  const password = "E2eModPassw0rd"
  const createResp = await request.post(`/api/v1/users/?school=${slug}`, {
    headers: { Authorization: `Bearer ${opToken}` },
    data: {
      email,
      password,
      role: "teacher",
      full_name: `E2E模块${label}教师`,
    },
  })
  expect(createResp.ok(), await createResp.text()).toBeTruthy()

  const loginResp = await request.post(
    `/api/v1/login/access-token?school=${slug}`,
    { form: { username: email, password } },
  )
  expect(loginResp.ok(), await loginResp.text()).toBeTruthy()
  const login = (await loginResp.json()) as { access_token: string }

  return { tenantId: tenant.id, slug, token: login.access_token }
}

async function setModule(
  request: APIRequestContext,
  opToken: string,
  tenantId: string,
  moduleKey: "speaking" | "vocabulary",
  enabled: boolean,
) {
  const resp = await request.put(
    `/api/v1/admin/tenants/${tenantId}/modules/${moduleKey}`,
    {
      headers: { Authorization: `Bearer ${opToken}` },
      data: { enabled, effective_at: null },
    },
  )
  expect(resp.ok(), await resp.text()).toBeTruthy()
}

test("只口语校与只单词校：/modules/me 下发与审计留痕", async ({ request }) => {
  // 1) 平台运营登录（仅 local 开放）
  const opResp = await request.post("/api/v1/login/platform-demo")
  expect(opResp.ok(), await opResp.text()).toBeTruthy()
  const opToken = ((await opResp.json()) as { access_token: string })
    .access_token

  // 2) 两校 + 教师
  const speakingOnly = await createSchoolWithTeacher(request, opToken, "sp")
  const vocabOnly = await createSchoolWithTeacher(request, opToken, "voc")

  // 3) 运营改写：A 只口语，B 只单词
  await setModule(request, opToken, speakingOnly.tenantId, "speaking", true)
  await setModule(request, opToken, speakingOnly.tenantId, "vocabulary", false)
  await setModule(request, opToken, vocabOnly.tenantId, "speaking", false)
  await setModule(request, opToken, vocabOnly.tenantId, "vocabulary", true)

  // 4) 教师拉取模块清单：口径与服务端闸门一致
  const spMe = await request.get("/api/v1/modules/me", {
    headers: { Authorization: `Bearer ${speakingOnly.token}` },
  })
  expect(spMe.ok(), await spMe.text()).toBeTruthy()
  const spModules = ((await spMe.json()) as { modules: string[] }).modules
  expect(spModules).toContain("speaking")
  expect(spModules).not.toContain("vocabulary")

  const vocabMe = await request.get("/api/v1/modules/me", {
    headers: { Authorization: `Bearer ${vocabOnly.token}` },
  })
  expect(vocabMe.ok(), await vocabMe.text()).toBeTruthy()
  const vocabModules = ((await vocabMe.json()) as { modules: string[] }).modules
  expect(vocabModules).toContain("vocabulary")
  expect(vocabModules).not.toContain("speaking")

  // 5) 审计：两校各留改写记录，前后值正确
  const spAudit = await request.get(
    `/api/v1/admin/tenants/${speakingOnly.tenantId}/modules/audit`,
    { headers: { Authorization: `Bearer ${opToken}` } },
  )
  expect(spAudit.ok(), await spAudit.text()).toBeTruthy()
  const spRows = (await spAudit.json()) as Array<{
    module_key: string
    enabled_after: boolean
  }>
  const spSpeaking = spRows.find((row) => row.module_key === "speaking")
  const spVocab = spRows.find((row) => row.module_key === "vocabulary")
  expect(spSpeaking?.enabled_after).toBe(true)
  expect(spVocab?.enabled_after).toBe(false)

  const vocabAudit = await request.get(
    `/api/v1/admin/tenants/${vocabOnly.tenantId}/modules/audit`,
    { headers: { Authorization: `Bearer ${opToken}` } },
  )
  expect(vocabAudit.ok(), await vocabAudit.text()).toBeTruthy()
  const vocabRows = (await vocabAudit.json()) as Array<{
    module_key: string
    enabled_after: boolean
  }>
  const vocabSpeaking = vocabRows.find((row) => row.module_key === "speaking")
  const vocabVocab = vocabRows.find((row) => row.module_key === "vocabulary")
  expect(vocabSpeaking?.enabled_after).toBe(false)
  expect(vocabVocab?.enabled_after).toBe(true)
})
