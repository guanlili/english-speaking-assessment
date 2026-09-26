"""AI 出题（老师侧）：按主题/档位起草情景问法，老师审改后入库。

PRD 红线：模型不当场给学生出唯一题（US-05）；这里只服务老师的题库起草，
学生端题目仍然全部来自内容表。
"""

from dataclasses import dataclass

from app.scoring.ark_client import ArkChatClient, ArkChatError, parse_json_list

# PRD §6 三档问法口径
BAND_SPECS = {
    "A2": "simple personal-fact or either-or questions (e.g. 'Do you like cats or dogs? Why?'), answerable in 15-20 seconds",
    "B1": "situational questions asking for preference, reasons, or a short example, answerable in about 30 seconds",
    "B2": "follow-up style questions requiring a sustained opinion with reasons, answerable in about 45 seconds; still everyday topics, NOT academic lectures",
}

QUESTION_SYSTEM_PROMPT = (
    "You draft speaking-practice questions for Chinese secondary school "
    "students learning English. Questions must be based on the given topic, "
    "match the requested CEFR band difficulty, be self-contained, and "
    "encourage students to speak. Respond with ONLY a JSON array (no "
    "markdown) of objects: "
    '[{"text": "<question>", "suggested_seconds": <int>}]'
)

MAX_GENERATE = 10


@dataclass
class DraftQuestion:
    text: str
    suggested_seconds: int


def build_generation_user_prompt(
    topic: str, band: str, count: int, hint: str | None
) -> str:
    lines = [
        f"Topic: {topic}",
        f"CEFR band: {band} — {BAND_SPECS[band]}",
        f"Generate exactly {count} different questions.",
    ]
    if hint:
        lines.append(f"Extra guidance from the teacher: {hint}")
    return "\n".join(lines)


def generate_draft_questions(
    topic: str, band: str, count: int, hint: str | None = None
) -> list[DraftQuestion]:
    if band not in BAND_SPECS:
        raise ValueError("band 必须是 A2/B1/B2")
    count = max(1, min(MAX_GENERATE, count))

    from app.core.config import settings

    client = ArkChatClient(
        api_key=settings.ARK_API_KEY, model=settings.ARK_RUBRIC_MODEL
    )
    content = client.chat(
        system=QUESTION_SYSTEM_PROMPT,
        user=build_generation_user_prompt(topic, band, count, hint),
        temperature=0.8,
    )
    items = parse_json_list(content)
    drafts: list[DraftQuestion] = []
    for item in items:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        try:
            seconds = int(item.get("suggested_seconds", 20))
        except TypeError, ValueError:
            seconds = 20
        drafts.append(
            DraftQuestion(text=text, suggested_seconds=max(10, min(60, seconds)))
        )
    if not drafts:
        raise ArkChatError("模型没有返回可用的问题")
    return drafts[:count]
