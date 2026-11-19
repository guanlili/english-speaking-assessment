# SpeakUp 火山账号换号手册（english-speaking-assessment）

> 盘点：2026-11-19　实施：2026-11-19
> 范围：仅 english-speaking-assessment（SpeakUp）
> 依据：仓库代码、两台生产机 `.env`、GitHub Secrets、新账号实测
> 本文只记变量名与 Key 后 4 位，不落完整密钥

## 1. 结论（TL;DR）

SpeakUp 原来依赖火山 **3 个产品、3 把 Key**；新账号开通方舟、录音文件识别 2.0、语音合成 2.0 后，收敛为 **2 把 Key**：

| 能力 | 新账号配置 | 状态 |
| --- | --- | --- |
| LLM（rubric 评分 / AI 出题 / 词汇 AI） | `ARK_API_KEY` 尾号 `7f94`，`doubao-seed-evolving` | 200，现网已切 |
| ASR（作答转写） | `VOLC_ASR_API_KEY` 尾号 `3def`，资源 `volc.seedasr.auc` | 200，现网已切 |
| TTS（教师标准音） | 同一把语音 Key，资源 `seed-tts-2.0` + `en_female_dacey_uranus_bigtts` | 200，现网已切 **直连** |

**VEI AI 网关不是必需。** 它只是过去方舟没有 `/audio/speech` 时的零代码绕行方案；现在豆包语音 2.0 直连已跑通，VEI 可以完全去掉。旧 `ARK_TTS_API_KEY` 只保留作回退，不再被现网消费。

`doubao-seed-2-0-lite-260428` 也已开通，但生产评分仍保留 `doubao-seed-evolving`：两组真实 rubric 样本里两者分数接近，evolving 的建议更细；按当前 755 次/月计算，成本差约 ¥3.6/月，远小于 ASR/TTS。要降本只需改 `ARK_RUBRIC_MODEL`，代码已同时支持两者。

> **生产拓扑（2026-11-19 实测）**：`outman.website` 解析到 `115.190.122.24`（现网新机，compose 项目 `esa`，路径 `/srv/english-speaking-assessment`），证书 `CN=outman.website`。`49.232.156.221`（`/opt/speakup`，compose 项目 `speakup`）是**遗留机**，已不再承接域名流量，保留作回滚/数据兜底。

---

## 2. 功能与模型映射

| 功能 | 接口 | 模型/资源 | Key | 失效表现 |
| --- | --- | --- | --- | --- |
| 问答题 rubric 评分 | 方舟 `/chat/completions` | `doubao-seed-evolving` | `ARK_API_KEY` | 分数「暂缺」，作答不失败，队列重试告警 |
| AI 出题 | 方舟 `/chat/completions` | `doubao-seed-evolving` | `ARK_API_KEY` | 接口 503 |
| 词汇 AI（草稿/讲解/洞察） | 方舟 `/chat/completions` | `doubao-seed-evolving` | `ARK_API_KEY` | 接口 503，确定性成绩不受影响 |
| 作答转写（ASR） | 豆包语音 `/api/v3/auc/bigmodel/recognize/flash` | 资源 `volc.seedasr.auc` | `VOLC_ASR_API_KEY` | 评分整条失败，队列堆积告警 |
| 标准音合成（TTS） | 豆包语音 `/api/v3/tts/unidirectional` | `seed-tts-2.0` + `en_female_dacey_uranus_bigtts` | `VOLC_TTS_API_KEY or VOLC_ASR_API_KEY` | 503；上传音频通道不受影响 |

代码兜底：

- `ASR_PROVIDER=ark` 时转写走方舟 `/responses` + `ARK_ASR_MODEL`，复用 `ARK_API_KEY`。当前生产不用，保留为备选。
- `TTS_PROVIDER=vei` 时回退 VEI 网关，Key 取 `ARK_TTS_API_KEY or ARK_API_KEY`。当前生产不用，保留为回滚路径。
- 直连 TTS 的 Key 取 `VOLC_TTS_API_KEY or VOLC_ASR_API_KEY`；默认复用语音 Key，少维护一把。

---

## 3. 模型：生产仍用 `doubao-seed-evolving`，lite 已开通可随时切

新账号最初没有开通 `doubao-seed-2-0-lite-260428`（返回 `ModelNotOpen`），所以先切到 `doubao-seed-evolving`。2026-11-19 晚 lite 已开通，实测 200。

| 模型 | 价格（输入/输出，元/百万 tokens） | 真实 rubric 样本 A（B1 旅行题） | 真实 rubric 样本 B（B2 观点题） |
| --- | --- | --- | --- |
| `doubao-seed-2-0-lite-260428` | 0.6 / 3.6 | 2/2/1/3，mock 4.0，6.02s | 3/3/2/3，mock 5.5，5.58s |
| `doubao-seed-evolving` | 6 / 30 | 3/2/2/4，mock 5.5，9.69s | 3/3/2/3，mock 5.5，7.68s |

- 两组样本都返回合法 JSON；lite 在第一组明显更严（语法 1、任务 3），第二组与 evolving 同分。
- evolving 的建议条数更多、引用原话更完整；但这是单样本观察，不是正式评测。
- 成本：按 10 月 755 次估算，evolving 约 ¥4/月，lite 约 ¥0.4/月；差约 ¥3.6/月。
- **建议**：评分继续用 evolving，稳定优先；若要降本，改 `ARK_RUBRIC_MODEL=doubao-seed-2-0-lite-260428`，同时把 `COST_LLM_CNY_PER_MTOK_IN/OUT` 改成 0.6/3.6，否则成本页会按 evolving 单价高估。

**关键坑：evolving 是推理模型，默认开思考。** 同一评分提示词实测：

| 模式 | 耗时 | completion tokens | 结果 |
| --- | --- | --- | --- |
| 默认（思考开） | 47.99s | 1459（其中 reasoning 1405） | JSON 正常，但队列会被拖垮 |
| `thinking: disabled` | 2.69s | 54 | JSON 正常 |

代码已在 `backend/app/scoring/ark_client.py` 的 `fast_chat_options()` 把 `doubao-seed-evolving` 和 `doubao-seed-2-0-lite-` 前缀都纳入快速档，自动发送：

```json
{"thinking": {"type": "disabled"}, "max_tokens": 2048}
```

---

## 4. ASR：新账号是「录音文件识别 2.0」，不是老极速版

| 资源 ID | 新账号结果 |
| --- | --- |
| `volc.bigasr.auc_turbo`（老极速版） | 403 `45000030 requested resource not granted` |
| `volc.bigasr.auc` | 403 同上 |
| `volc.seedasr.auc`（录音文件识别 2.0） | **200**，返回 `Hello, this is a test of speech recognition.` |

代码已把资源 ID 从写死改成配置项：

- `backend/app/core/config.py`：`VOLC_ASR_RESOURCE_ID: str = "volc.bigasr.auc_turbo"`（默认向后兼容）
- `backend/app/scoring/volc_flash.py`：`VolcFlashAsr(..., resource_id=...)`，请求头 `X-Api-Resource-Id` 使用该值
- `backend/app/scoring/worker.py`：从 settings 注入
- `scripts/generate-deploy-env.sh` + `.github/workflows/deploy.yml`：部署时注入 `VOLC_ASR_RESOURCE_ID`

新账号生产值：`VOLC_ASR_RESOURCE_ID=volc.seedasr.auc`。

---

## 5. TTS：已改豆包语音 2.0 直连，VEI 不再是必需

### 5.1 为什么以前用 VEI

方舟域名没有 OpenAI 兼容的 `/audio/speech`。VEI AI 网关提供：

```text
POST https://ai-gateway.vei.volces.com/v1/audio/speech
Authorization: Bearer <VEI 网关 Key>
```

它接起来最省事，但代价是**多一个控制台、多一把与方舟/语音都不通用的 Key**。对 SpeakUp 来说，这不是架构上的必需，只是当时的零代码路径。

### 5.2 新账号实际开通的是「语音合成 2.0」

| 请求 | 结果 |
| --- | --- |
| `seed-tts-1.0` + `en_female_anna_mars_bigtts` | 403 `45000030 [resource_id=volc.service_type.10029] requested resource not granted` |
| `volc.service_type.10030` / `volc.service_type.10029` | 403 同上 |
| `seed-tts-2.0` + `en_female_anna_mars_bigtts`（1.0 音色） | HTTP 200，但 body `{"code":55000000,"message":"resource ID is mismatched with speaker related resource"}` |
| `seed-tts-2.0` + `en_female_dacey_uranus_bigtts`（2.0 音色） | **200，音频分片正常** |
| `seed-tts-2.0` + `en_male_tim_uranus_bigtts`（2.0 音色） | **200，音频分片正常** |

结论：**用户开通的是 2.0，不是 1.0**。1.0 音色（`_mars_bigtts` / `_moon_bigtts` 等）不能配 2.0 资源；2.0 音色命名以 `_uranus_bigtts` 结尾。

### 5.3 直连协议

```text
POST https://openspeech.bytedance.com/api/v3/tts/unidirectional
X-Api-Key: <VOLC_ASR_API_KEY>
X-Api-Resource-Id: seed-tts-2.0
X-Api-Request-Id: <uuid>
Content-Type: application/json

{"user":{"uid":"speakup"},"req_params":{"text":"...","speaker":"en_female_dacey_uranus_bigtts","audio_params":{"format":"mp3","sample_rate":24000}}}
```

响应是 HTTP Chunked 的 JSON 行，不是纯二进制：

```json
{"code":0,"data":"<base64 音频分片>"}
...
{"code":20000000,"message":"OK"}
```

代码把每行 `data` base64 解码后按顺序拼接；`code=0` 是分片，`code=20000000` 是结束/成功，其他 code 报错。

### 5.4 音色选择

2.0 英文音色候选：

| 音色 | Speaker ID | 说明 |
| --- | --- | --- |
| Dacey | `en_female_dacey_uranus_bigtts` | 美式英语女声，温暖、清晰，当前生产用 |
| Stokie | `en_female_stokie_uranus_bigtts` | 美式英语女声，年轻、口语化 |
| Tim | `en_male_tim_uranus_bigtts` | 美式英语男声，清晰 |
| Tina 老师 2.0 | `zh_female_yingyujiaoxue_uranus_bigtts` | 中英，教育场景 |

换成 Dacey 后，内容缓存键由 `(model, voice, text)` 变成 `(seed-tts-2.0, en_female_dacey_uranus_bigtts, text)`，旧 VEI 生成的缓存不会误命中。

### 5.5 三条路对比

| 方案 | 做法 | Key 数量 | 代码改动 | 当前状态 |
| --- | --- | --- | --- | --- |
| A. VEI 网关 | 在 `console.volcengine.com/vei/aigateway` 建 Key | 3 | 0 | 仅回退，不再使用 |
| B. 豆包语音直连 | `/api/v3/tts/unidirectional`，复用语音 Key | 2 | 已改 `tts.py` + 测试 | **当前生产** |
| C. 不用自动合成 | 教师上传现成音频 | 2 | 0 | 系统本来就支持上传通道 |

**结论：VEI 不是严格必需。** 现在直连已落地，旧 `ARK_TTS_API_KEY` 只保留作回退；观察 1–2 周无问题后，旧 VEI Key 可以停用。

> 注意：`ARK_TTS_API_KEY` 与 `ARK_API_KEY` 不通用；不要把方舟 Key 填到 TTS 上。直连模式下它根本不会被读取。

---

## 6. 配置矩阵

| 变量 | 代码默认 | 现网生产（`115.190.122.24`） | 遗留机（`49.232.156.221`） |
| --- | --- | --- | --- |
| `SCORING_PROVIDER` | `mock` | `ark` | `ark` |
| `ASR_PROVIDER` | `ark` | `volc_flash` | `volc_flash` |
| `ARK_RUBRIC_MODEL` | `doubao-seed-2-0-lite-260428` | `doubao-seed-evolving` | `doubao-seed-evolving` |
| `ARK_ASR_MODEL` | `doubao-seed-2-0-lite-260428` | `doubao-seed-evolving` | `doubao-seed-evolving` |
| `VOLC_ASR_RESOURCE_ID` | `volc.bigasr.auc_turbo` | `volc.seedasr.auc` | `volc.seedasr.auc` |
| `TTS_PROVIDER` | `vei` | `volc_direct` | `volc_direct` |
| `VOLC_TTS_RESOURCE_ID` | `seed-tts-2.0` | `seed-tts-2.0` | `seed-tts-2.0` |
| `VOLC_TTS_VOICE` | `en_female_dacey_uranus_bigtts` | 同默认 | 同默认 |
| `VOLC_TTS_API_KEY` | 空（回落 `VOLC_ASR_API_KEY`） | 空 | 空 |
| `ARK_TTS_API_KEY` | 空 | 旧 VEI Key（仅回退） | 旧 VEI Key（仅回退） |
| `ARK_TTS_MODEL` | `doubao-tts` | 同默认（仅 VEI 回退用） | 同默认 |
| `ARK_TTS_VOICE` | `en_female_anna_mars_bigtts` | 同默认（仅 VEI 回退用） | 同默认 |

Key 存放矩阵：

| 位置 | `ARK_API_KEY` | `VOLC_ASR_API_KEY` | `ARK_TTS_API_KEY` |
| --- | --- | --- | --- |
| GitHub Secrets（仓库级 + `production` Environment 级） | 新 Key | 新 Key | 旧 Key（仅回退） |
| 现网生产 `.env`（`/srv/english-speaking-assessment`） | 新 Key | 新 Key | 旧 Key（仅回退） |
| 遗留机 `.env`（`/opt/speakup`） | 新 Key（手工同步） | 新 Key（手工同步） | 旧 Key（仅回退） |
| 本地 `.env` | 空（mock） | 空 | 空 |

---

## 7. 已实施的切换

### 7.1 代码（第一批：ASR + 模型）

分支 `feat/volc-account-switch`，PR #497，提交 `84050a3`：

- ASR 资源 ID 可配置，新增 `VOLC_ASR_RESOURCE_ID`
- `doubao-seed-evolving` 自动关思考
- 成本口径改为 evolving 6/30
- 部署脚本与 workflow 注入新变量
- 新增自定义资源 ID 单元测试
- `.env.example` 模型改为 evolving

### 7.2 现网生产（`115.190.122.24` / `outman.website`）

- 域名实测解析到 `115.190.122.24`，证书 `CN=outman.website`；compose 项目 `esa`
- 写入新 Key、`volc.seedasr.auc`、evolving；验证后切回 `master`
- 重建 `esa-backend`，容器 healthy
- 容器内真实调用验证：
  - ASR：返回 `Hello, this is a test of speech recognition.`
  - LLM：2.51s 返回合法评分 JSON
- 从 Mac Mini 外部访问 `https://outman.website/` 与 `/api/v1/utils/health-check/` 均 200

### 7.3 遗留机（`49.232.156.221` / `speakup`）

- 不再是 DNS 目标，仅作回滚/数据兜底
- 已同步代码到 `84050a3`，写入同一套新 Key；后端曾 Exited 137，恢复后完成 ASR / LLM 验证（LLM 1.42s），随后停回原状态，避免旧队列被 8 个 worker 重复消费
- 本次 TTS 直连后，`.env` 已同步 `TTS_PROVIDER=volc_direct`、`seed-tts-2.0`、Dacey；备份 `.env.bak-tts-direct-20261120-004454`。后端仍停用。

### 7.4 GitHub Secrets

- 仓库级与 `production` Environment 级都已更新：
  `ARK_API_KEY`、`VOLC_ASR_API_KEY`、`VOLC_ASR_RESOURCE_ID`、`ARK_RUBRIC_MODEL`、`ARK_ASR_MODEL`
- 本次新增（仓库级 + `production` Environment 级）：
  `TTS_PROVIDER=volc_direct`、`VOLC_TTS_RESOURCE_ID=seed-tts-2.0`、`VOLC_TTS_VOICE=en_female_dacey_uranus_bigtts`
- `VOLC_TTS_API_KEY` 未设置，留空即回落 `VOLC_ASR_API_KEY`
- `ARK_TTS_API_KEY` 仍是旧值，只作 VEI 回退
- 部署工作流 `deploy.yml` 的 deploy job 绑定了 `environment: production`，**环境级 Secret 优先于仓库级**；只改仓库级会被旧环境值覆盖

### 7.5 TTS 直连（本次，PR #501）

分支 `feat/volc-tts-direct`，最终 master 提交 `c4204f3`，PR #501 已 MERGED。

代码：

- `backend/app/scoring/tts.py` 新增 `VolcDirectTtsProvider`
  - POST `/api/v3/tts/unidirectional`
  - 解析 chunked JSON 行 + base64 `data`
  - 兼容 `code=0`（分片）与 `code=20000000`（结束/成功）
- `backend/app/core/config.py` 新增：
  `TTS_PROVIDER`、`VOLC_TTS_BASE_URL`、`VOLC_TTS_API_KEY`、`VOLC_TTS_RESOURCE_ID`、`VOLC_TTS_VOICE`
- `build_tts_provider()` 按 `TTS_PROVIDER` 返回 VEI 或直连；直连 Key 回落 `VOLC_ASR_API_KEY`
- `metrics.py` 的 TTS 指标显示 `provider`、资源 ID、音色
- `scripts/generate-deploy-env.sh` 与 `deploy.yml` 注入 `TTS_PROVIDER` / `VOLC_TTS_*`
- 新增直连单测：Key 缺失、音频分片拼接、`55000000` 错误码、provider 切换

生产部署（run `44566531438`，`CI & Deploy` 成功）：

- `esa-backend-1` 重建后 healthy
- 现网 `.env`：
  `TTS_PROVIDER="volc_direct"`、`VOLC_TTS_RESOURCE_ID="seed-tts-2.0"`、`VOLC_TTS_VOICE="en_female_dacey_uranus_bigtts"`、`VOLC_TTS_API_KEY=""`
- 容器内 provider 实测：
  `provider: volc_direct seed-tts-2.0 en_female_dacey_uranus_bigtts`
  `audio bytes: 34029 head: b'ID3\x04'`
- 走真实后台 API（登录 + `/api/v1/admin/audio/tts`）：
  HTTP 200，返回 `/api/v1/audio/content/tts-08d40d5fbf937debd4c5073d9da5ba8b2c161670.mp3`
- 外部回放该 URL：HTTP 200，29,229 字节，`MPEG ADTS, layer III, v2, 64 kbps, 24 kHz, Monaural`
- 外部健康检查：`https://outman.website/`、`/api/v1/utils/health-check/`、`/api/v1/utils/ready-check/` 均 200

### 7.6 CI 异常

- 早前 master run `44550824170` 卡在 E2E「安装依赖与 Chromium/WebKit」20+ 分钟，deploy job 未启动，已取消；同日 #498 触发的 run `44555763309` 成功（2m59s）
- 本次 PR 期间 E2E 也出现过 Playwright 安装慢/被新提交取消；重跑后全绿，属于 runner 冷缓存/网络偶发，不是代码问题
- 后续若再遇到，优先重跑失败 job 或利用热缓存，不要盲目改代码

---

## 8. 验证清单

现网生产（`115.190.122.24`，域名实测目标）：

- [x] `esa-backend` healthy
- [x] ASR 真实音频转写成功
- [x] LLM 评分 JSON 成功（2.51s）
- [x] TTS 直连 provider 200，34,029 字节合法 MP3
- [x] TTS 后台 API 200，29,229 字节合法 MP3
- [x] `https://outman.website/` 200
- [x] `/api/v1/utils/health-check/` 200
- [x] `/api/v1/utils/ready-check/` 200
- [ ] 管理后台 ASR / LLM / TTS 有新调用计数、失败率 0（需平台运营账号登录后台抽查）
- [ ] 教师端生成一条标准音、学生端做一道开放题人工确认
- [ ] 新账号控制台看到方舟、语音合成、录音识别调用量
- [ ] 旧账号除 TTS 回退 Key 外无新增调用

遗留机（`49.232.156.221`，非 DNS 目标）：

- [x] 恢复期间 `speakup-backend` healthy
- [x] ASR 真实音频转写成功
- [x] LLM 评分 JSON 成功（1.42s）
- [x] TTS 直连环境变量已同步
- [x] 验证后停回，避免旧队列消费

观察 24–48 小时：

- [ ] 评分队列无异常积压
- [ ] 失败率与基线持平
- [ ] 标准音无空文件/0 字节
- [ ] 旧账号无新增 TTS 调用

---

## 9. 回滚

1. 旧 Key 在禁用前一直有效。
2. **只回滚 TTS**（推荐，代码不用回退）：
   - 现网 `.env` 设 `TTS_PROVIDER=vei`
   - 确认 `ARK_TTS_API_KEY` 仍是旧 VEI Key
   - `docker compose -f compose.yml up -d backend`
   - 缓存键会从 `seed-tts-2.0|Dacey|text` 回到 `doubao-tts|anna|text`，旧缓存仍可用
3. **整机回滚**：
   - 现网：还原 `/srv/english-speaking-assessment/.env.env.bak.20261119-224841` → `docker compose -f compose.yml up -d backend`
   - 遗留机：还原 `/opt/speakup/.env.bak-volc-switch-20261119-231808`（或本次 `.env.bak-tts-direct-20261120-004454`）→ `docker compose -f compose.yml up -d`
4. GitHub Secrets：仓库级与 `production` Environment 级都改回旧值 → 重跑 `deploy.yml`。
5. 旧 Key 已禁用：去旧账号重新启用（未删除即可恢复）。

**原则：新 Key 未验证通过前，旧 Key 绝不禁用。** TTS 直连已验证，旧 VEI Key 可以留 1–2 周再停。

---

## 10. 常见坑

| # | 坑 | 规避 |
| --- | --- | --- |
| 1 | ASR 资源 ID 用错，403 `45000030` | 新账号填 `volc.seedasr.auc`；老账号才是 `volc.bigasr.auc_turbo` |
| 2 | evolving 开思考，单次 48s / 1459 token | `fast_chat_options` 自动 `thinking: disabled` |
| 3 | 模型短名 404 | lite 必须带日期后缀；evolving 本身无日期后缀，按前缀匹配 |
| 4 | 手改生产 `.env` 后被覆盖 | 改 GitHub Secrets，走流水线 |
| 5 | 2.0 资源配 1.0 音色 | HTTP 200 + `code=55000000 resource ID is mismatched`；2.0 音色必须 `_uranus_bigtts` |
| 6 | 1.0 资源未开通 | `seed-tts-1.0` 返回 403 `45000030 [resource_id=volc.service_type.10029]` |
| 7 | 把 `code=20000000` 当错误 | 它是 TTS 流结束/成功码；只有非 0/非 20000000 才是错误 |
| 8 | 三把 Key 互相替代 | 方舟、豆包语音是两套凭证；VEI 旧 Key 只回退，直连不读 |
| 9 | 只改一台机器 | 两台机必须同步；遗留机虽停用，回滚时也要能起 |
| 10 | 旧账号提前停用 | 先确认 TTS 直连/API 回放通过，再停旧 VEI Key |
| 11 | 只改仓库级 Secrets | deploy job 绑定 `production` Environment，环境级 Secret 优先；必须同时改 Environment 级 |
| 12 | 把 `49.232.156.221` 当成现网 | `outman.website` 实测解析到 `115.190.122.24`；用 `curl -v` 或 socket 确认后再操作 |
| 13 | master 部署卡在 Playwright 安装 | 同提交 PR 检查已过时可重跑；长期修 E2E runner 缓存/镜像 |
| 14 | 2.0 音色返回 200 但 0 字节 | 旧网关对不存在音色会这样；直连 provider 已按“无音频”报错，不落缓存 |

---

## 11. 成本

| 项目 | 10 月真实用量 | 单价 | 估算 |
| --- | --- | --- | --- |
| ASR 录音文件识别 2.0 | 10.69h | ¥4.5/h（30h 包约 ¥4.4/h） | 约 ¥48/月 |
| 方舟 LLM（evolving，关思考） | 755 次 | 输入 ¥6/百万、输出 ¥30/百万 | 约 ¥4/月 |
| 方舟 LLM（lite，若切换） | 755 次 | 输入 ¥0.6/百万、输出 ¥3.6/百万 | 约 ¥0.4/月 |
| 豆包语音合成 2.0 | 97 条，2–4 万字符 | ¥2.8/万字符（10 万字符 ¥28） | 约 ¥6–11/月 |
| VEI TTS（仅回退，不再产生） | 97 条，2–4 万字符 | ¥5/万字符 | 回退时才会计费 |

全校铺开后 AI 成本约 ¥200–900/月，按 ¥1,000/月封顶预算即可（详见 `docs/pricing-assessment-2026-10.md`；该文档仍是 lite 口径，成本页以本文为准）。

---

## 12. 新 Key 台账

| 用途 | 变量名 | 尾号 | 创建日期 | 存放 | 验证 |
| --- | --- | --- | --- | --- | --- |
| 方舟 LLM | `ARK_API_KEY` | `7f94` | 2026-11-19 | GH Secrets + 两台机 `.env` | 200，evolving 评分 2.5s |
| 豆包语音（ASR + TTS） | `VOLC_ASR_API_KEY` | `3def` | 2026-11-19 | GH Secrets + 两台机 `.env` | ASR 200；TTS 2.0 200 / 34,029 字节 |
| VEI TTS（仅回退） | `ARK_TTS_API_KEY` | 旧 Key | — | GH Secrets + 两台机 `.env` | 旧 provider 仍可 200；直连不读 |

---

## 13. 变更记录

| 日期 | 操作 | 结果 |
| --- | --- | --- |
| 2026-11-19 | 完成火山依赖盘点 | 3 产品 3 Key、2 台机同一套旧 Key |
| 2026-11-19 | 新账号开通方舟 + 录音文件识别 2.0 | 2 把 Key 验证 200 |
| 2026-11-19 | 代码支持资源 ID 可配置、evolving 关思考 | PR #497 MERGED |
| 2026-11-19 | 新机（现网）切换 | ASR / LLM 实测通过 |
| 2026-11-19 | 更新 GitHub Secrets（仓库级 + production Environment 级） | 已更新并生效 |
| 2026-11-19 | 确认 `outman.website` 已解析到新机 `115.190.122.24` | 现网生产在新机 |
| 2026-11-19 | 现网新机重建后端并用新 Key 验证 | ASR / LLM 通过，域名 200 |
| 2026-11-19 | 遗留机后端 Exited 137，手工同步代码/新 Key 并恢复验证 | 验证通过后停回 |
| 2026-11-19 | master CI 卡在 Playwright 安装，取消后手工部署 | 部署完成 |
| 2026-11-19 | #498 合并触发流水线部署成功（2m59s） | 生产由流水线重建，CI 恢复 |
| 2026-11-19 | 新账号开通语音合成 2.0；确认 1.0 未授权 | `seed-tts-2.0` 200，1.0 403 |
| 2026-11-19 | 新增豆包语音直连 TTS provider | PR #501 MERGED（`c4204f3`） |
| 2026-11-19 | 生产流水线 run `44566531438` 成功 | `esa-backend` 重建 healthy |
| 2026-11-19 | 现网直连 TTS provider / 后台 API 实测 | 200，34,029 / 29,229 字节合法 MP3 |
| 2026-11-19 | 新账号开通 lite；对比 evolving | lite 200；生产暂留 evolving |
| 2026-11-19 | 遗留机 `.env` 同步直连 TTS | 备份 `.env.bak-tts-direct-20261120-004454`，后端仍停 |
