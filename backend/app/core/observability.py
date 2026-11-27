"""错误监控（自建 GlitchTip，Sentry 协议）初始化集中处。

- DSN 为空或本地环境时不初始化：SDK 不加载、不发任何上报。
- 默认不采集 PII：不挂用户标识/IP/Cookie/认证头，不上报请求体；
  客户端能拿到的只有异常堆栈、路由名与环境标签。IP 在 GlitchTip 项目侧
  再做匿名化（`scrub_ip_addresses=True`）。
"""

import sentry_sdk

from app.core.config import settings


def init_sentry() -> None:
    """按配置初始化 Sentry/GlitchTip SDK；未配置 DSN 时静默跳过。"""
    if not settings.SENTRY_DSN or settings.ENVIRONMENT == "local":
        return

    sentry_sdk.init(
        dsn=str(settings.SENTRY_DSN),
        environment=settings.ENVIRONMENT,
        enable_tracing=True,
        # 全采样在 40 人课堂并发下会刷配额，0.1 起步。
        traces_sample_rate=0.1,
        # 显式关闭 PII 采集：不传用户、IP、Cookie、Authorization。
        send_default_pii=False,
    )
