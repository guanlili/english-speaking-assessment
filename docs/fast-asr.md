# 极速转写试用

默认保留方舟 Responses 转写。豆包语音极速版使用独立凭证，不复用 ARK_API_KEY。

1. 在火山豆包语音控制台开通 `volc.bigasr.auc_turbo`，获取新版控制台 API Key。
2. 本地 `.env` 设置 `SCORING_PROVIDER=ark`、`ASR_PROVIDER=volc_flash`、`VOLC_ASR_API_KEY=<语音 Key>`，保留 `ARK_API_KEY` 用于详细评分。不要提交密钥。
3. 重建后端容器以加载环境变量。生产通过同名 GitHub Secrets 和部署流水线设置，不手改生产 `.env`。
4. 日志 `ASR` 行含 provider、conversion_ms、recognition_ms，不记录音频或转写正文。
5. 用同一批经授权的学生英语录音比较两种服务：人工核对漏词、替换、重复词，记录停止录音到展示结果的中位数和 P95，再测试全班并发。

回退：将 `ASR_PROVIDER` 改为 `ark`，重新加载后端环境。不自动回退，避免新服务失败时增加等待时间或掩盖配置错误。

此版本仍为录完后上传，不是流式识别。关闭 enable_ddc 和 enable_itn，保留重复、口头词和数字原始表达；不把参考答案作为转写提示。速度和准确率需真实录音验证。

接口依据：https://www.volcengine.com/docs/6561/1631584
