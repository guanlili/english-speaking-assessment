"""列表端点的可选分页：offset + limit（limit=None 表示不封顶）。

与既有 admin 路由的 skip/limit 范式一致：不传 limit 时行为完全不变，
调用方可以主动收窄；响应结构保持 list，无需改动前端客户端。
"""

from typing import Any


def paged(statement: Any, offset: int = 0, limit: int | None = None) -> Any:
    """给 Select 语句加可选 offset/limit；limit=None 不封顶。

    路由函数被内部直接调用（如 POST 收藏后回读列表）时不会经过 FastAPI
    的参数解析，默认值可能是 Query(...) 对象而非标量；非 int 一律按"未传"
    处理，保持全量语义，避免把 Query 对象塞进 SQL 的 OFFSET/LIMIT。
    """
    if isinstance(offset, int) and not isinstance(offset, bool) and offset > 0:
        statement = statement.offset(offset)
    if isinstance(limit, int) and not isinstance(limit, bool):
        statement = statement.limit(limit)
    return statement
