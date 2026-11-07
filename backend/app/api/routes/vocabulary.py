"""词汇学习（背单词）模块接口。

按域拆分（2026-11-07）：实现散在 routes/vocabulary_*.py，本文件只做装配，
保证 /api/v1/vocabulary 与 /classes/{code}/vocabulary 的路径、参数、
响应模型完全不变。

    vocabulary_shared       router 之外的跨域辅助（组装/权限/结果载荷）
    vocabulary_import       CSV 导入预览（不落库）
    vocabulary_books        词库 CRUD + 词条编辑（教师/管理员）
    vocabulary_assignments  课堂发布 / 学生任务 / 作答 / 结果（教师 + 学生）
    vocabulary_quiz         测验成绩发布、补考、答卷、CSV 导出
    vocabulary_student      错词本 / 自主练习 / 学习历史（学生）

注册顺序按下面对 include_router 的调用顺序固定（= 拆分前原文件端点的
定义顺序），避免 import 排序改变 OpenAPI 操作顺序、导致前端客户端漂移。

权限口径（设计文档 §5）：词库编辑/发布 = 课堂所有者教师或管理员；
学生任务仅目标名单内的本班学生；原始作答仅本人与该班教师可读。
401 只表示登录失效；权限不足一律 403。
"""

from fastapi import APIRouter

from app.api.routes import (
    vocabulary_assignments as _assignments,
)
from app.api.routes import (
    vocabulary_books as _books,
)
from app.api.routes import (
    vocabulary_import as _import,
)
from app.api.routes import (
    vocabulary_quiz as _quiz,
)
from app.api.routes import (
    vocabulary_student as _student,
)

router = APIRouter()

router.include_router(_import.router, tags=["vocabulary"])
router.include_router(_books.router, tags=["vocabulary"])
router.include_router(_assignments.router, tags=["vocabulary"])
router.include_router(_quiz.router, tags=["vocabulary"])
router.include_router(_student.router, tags=["vocabulary"])

__all__ = ["router"]
