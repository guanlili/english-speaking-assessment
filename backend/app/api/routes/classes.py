"""课堂路由门面。

实现按资源拆分：共享助手与课堂 CRUD 在 class_shared，学生练习计划在
class_today_plan，教师面板在 class_board，成长轨迹在 class_progress，
考试/听音/确认运行时在 class_runtime，发布指派在 class_assignments，
句型收藏在 class_frames。本文件保留历史导入路径（vocab_* 路由与测试
经 app.api.routes.classes 取共享助手），main.py 仍从此处取 router。
"""

from app.api.routes import (  # noqa: F401  # 端点注册副作用
    class_assignments,
    class_board,
    class_frames,
    class_progress,
    class_runtime,
    class_today_plan,
)
from app.api.routes.class_shared import (  # noqa: F401
    _get_classroom,
    _require_classroom_teacher,
    _student_profile_of,
    _today_in_practice_tz,
    router,
)
