"""请求关联 ID；线程池任务显式复制 context，日志不记录凭证或题目正文。"""

import os
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

request_id: ContextVar[str] = ContextVar("request_id", default="background")
PROCESS_INFO = {
    "instance_id": uuid.uuid4().hex,
    "pid": os.getpid(),
    "started_at": datetime.now(UTC).isoformat(),
}
