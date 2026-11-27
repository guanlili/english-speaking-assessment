"""PK 容量探针的独立副本进程（dev-only，被 `pk_capacity_probe.py` 拉起）。

双副本模式下，探针父进程把本脚本作为**独立 OS 子进程**拉起两例，连接同一个
本地探针合成库：与父进程内起线程的「单进程双线程」形态明确区分——两个副本
是各自独立的 uvicorn 进程，跨副本状态只能经数据库可见，用来实测多实例下的
作答延迟与跨副本传播延迟。

环境变量（均由父进程注入，不内置默认值）：

- ``PK_PROBE_DATABASE_URI``：探针库 DSN（必填）；
- ``PK_PROBE_PORT``：监听端口（必填）；
- ``PK_PROBE_REPLICA_ID``：副本编号（仅用于日志/报告标注）。

安全闸与 `pk_capacity_probe.py` 同口径：仅 ``ENVIRONMENT=local`` 且目标为主机
本机；不放宽去连远端。
"""

import os
import sys
from pathlib import Path

# 必须在导入 app 之前屏蔽真实评分调用（与 tests/conftest.py 同口径）
os.environ.setdefault("SCORING_PROVIDER", "mock")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _refuse_unsafe_target() -> None:
    from urllib.parse import urlparse

    from app.core.config import settings

    if settings.ENVIRONMENT != "local":
        raise SystemExit(
            f"仅允许 ENVIRONMENT=local 运行（当前 {settings.ENVIRONMENT}）"
        )
    parsed = urlparse(os.environ["PK_PROBE_DATABASE_URI"])
    if parsed.hostname not in _LOCAL_HOSTS:
        raise SystemExit(f"目标实例不是本机（{parsed.hostname}），拒绝运行")


def main() -> int:
    uri = os.environ.get("PK_PROBE_DATABASE_URI", "").strip()
    port = os.environ.get("PK_PROBE_PORT", "").strip()
    replica_id = os.environ.get("PK_PROBE_REPLICA_ID", "0").strip()
    if not uri or not port:
        raise SystemExit("缺少 PK_PROBE_DATABASE_URI / PK_PROBE_PORT 环境变量")

    _refuse_unsafe_target()

    from sqlalchemy import create_engine

    from app.core.db import set_engine
    from app.core.tenant_context import install_tenant_bind

    # 池上限对齐 40 通道 + 作答并发（与探针父进程同口径）
    engine = create_engine(uri, pool_pre_ping=True, pool_size=20, max_overflow=20)
    install_tenant_bind(engine)
    set_engine(engine)

    import uvicorn

    from app.main import app

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=int(port),
        log_level="error",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    print(f"[probe-replica {replica_id}] listening 127.0.0.1:{port}", flush=True)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
