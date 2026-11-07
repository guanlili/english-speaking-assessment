"""词汇模型：学生作答会话（拆分自 app/models/vocabulary.py，2026-11-07）。"""

import uuid

from sqlmodel import Field, SQLModel


class VocabularySessionCreate(SQLModel):
    """创建/恢复作答会话：缺省 assignment_id = 聚焦任务。"""

    assignment_id: uuid.UUID | None = None
    # round="new"：全部轮次已结束时开新的复习轮（round_no=max+1）；
    # continue/缺省=续做未结束轮（全结后 422，不新建）
    round: str | None = Field(default=None, max_length=8)


class VocabularyAnswerRequest(SQLModel):
    item_index: int = Field(ge=0)
    prompt_type: str = Field(default="meaning", max_length=16)
    answer: str = Field(min_length=1, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=64)


class VocabularyAnswerResult(SQLModel):
    item_index: int
    attempt_no: int
    is_correct: bool
    # 标准拼写（首答后即揭示；练习重试对错即时反馈）
    correct_spelling: str
    meaning_zh: str
    session_status: str
    answered_count: int
    correct_first_count: int


class VocabularyQuizAnswerReceipt(SQLModel):
    """测验作答回执：只确认已接收，不返回答案与正误（防提前泄露）。"""

    item_index: int
    received: bool = True
    answered_count: int
    session_status: str
    # 服务器计算的剩余秒数（客户端倒计时只是展示）
    remaining_seconds: int | None = None
