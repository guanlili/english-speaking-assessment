"""词汇班内学习榜：课堂级设置与学生参与档案（#517）。

口径冻结（见 docs/module-notes.md「背单词模块」榜单小节）：

- **设置默认不落种子**：数据库无行时由服务层返回默认值
  （enabled=true / audience="teachers" / anonymous=true / top_n=10）。
- **参与档案**：学生默认无 participant 行即未参加；加入时在班内稳定分配
  ``alias_no``，退出后重新加入复用同一编号。
- **隐私**：匿名时条目只下发 alias_no，不下发姓名；响应不含
  student_id / user_id / 邮箱。
"""

import uuid
from datetime import date, datetime
from typing import Literal

from sqlalchemy import (
    DateTime,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.models.base import (
    _tenant_id_field,
    get_datetime_utc,
)

# 可见范围：teachers = 仅本班教师/管理员可见；students = 放开给本班学生
AUDIENCE_TEACHERS = "teachers"
AUDIENCE_STUDENTS = "students"
LEADERBOARD_AUDIENCES = (AUDIENCE_TEACHERS, AUDIENCE_STUDENTS)

# 榜单固定取前 N 名（允许第 N 名并列导致行数 > N）
LEADERBOARD_TOP_N = 10


class VocabularyLeaderboardSetting(SQLModel, table=True):
    """课堂级榜单开关与隐私口径（一班一行；无行走服务层默认值）。"""

    __tablename__ = "vocabulary_leaderboard_setting"
    __table_args__ = (
        UniqueConstraint("classroom_id", name="uq_vocab_leaderboard_setting_classroom"),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE", index=True
    )
    # false = 整班关闭榜单（教师设置页仍可预览，学生 403）
    enabled: bool = Field(default=True, sa_column_kwargs={"server_default": "true"})
    # teachers = 仅教师可见；students = 放开给本班参加学生
    audience: str = Field(
        default=AUDIENCE_TEACHERS,
        max_length=16,
        sa_column_kwargs={"server_default": AUDIENCE_TEACHERS},
    )
    # true = 匿名编号展示；false = 展示学生 display_name
    anonymous: bool = Field(default=True, sa_column_kwargs={"server_default": "true"})
    updated_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL", index=True
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class VocabularyLeaderboardParticipant(SQLModel, table=True):
    """学生在某班榜单的参与档案：加入/退出状态与稳定匿名编号。"""

    __tablename__ = "vocabulary_leaderboard_participant"
    __table_args__ = (
        UniqueConstraint(
            "classroom_id",
            "student_id",
            name="uq_vocab_leaderboard_participant_student",
        ),
        UniqueConstraint(
            "classroom_id",
            "alias_no",
            name="uq_vocab_leaderboard_participant_alias",
        ),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE", index=True
    )
    student_id: uuid.UUID = Field(
        foreign_key="student.id", nullable=False, ondelete="CASCADE", index=True
    )
    active: bool = Field(default=True, sa_column_kwargs={"server_default": "true"})
    # 班内稳定编号：加入时分配，退出后重新加入复用；班内唯一
    alias_no: int = Field(ge=1)
    joined_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    left_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# ── 请求 / 响应体（非表）─────────────────────────────────────────────


class VocabularyLeaderboardSettings(SQLModel):
    """榜单设置投影（无库行时由服务层填默认值）。"""

    enabled: bool
    audience: str
    anonymous: bool
    top_n: int = LEADERBOARD_TOP_N


class VocabularyLeaderboardSettingsUpdate(SQLModel):
    """教师更新榜单设置。"""

    enabled: bool
    audience: Literal["teachers", "students"]
    anonymous: bool


class VocabularyParticipationUpdate(SQLModel):
    """学生加入 / 退出榜单。"""

    joined: bool


class VocabularyParticipationState(SQLModel):
    """加入状态回执：alias_no 退出后为 null，重新加入复用原编号。"""

    joined: bool
    alias_no: int | None = None


class VocabularyLeaderboardEntry(SQLModel):
    """榜单条目：匿名时 display_name 为 null，只带 alias_no。"""

    rank: int
    score: int
    alias_no: int
    display_name: str | None = None
    suffix: str | None = None


class VocabularyLeaderboardView(SQLModel):
    """GET /classes/{code}/vocabulary/leaderboard 响应。"""

    week_start: date
    settings: VocabularyLeaderboardSettings
    entries: list[VocabularyLeaderboardEntry] = []
    my_entry: VocabularyLeaderboardEntry | None = None
    my_rank: int | None = None
    my_score: int = 0
    # 当前学生 viewer 是否有 active 参与档案；教师 viewer 固定 false
    joined: bool = False
    # 教师可见参与人数；学生视角一律 null（未参加学生看不到人数）
    participant_count: int | None = None
