from sqlmodel import Session, create_engine, select

from app import crud
from app.core.config import settings
from app.models import (
    Classroom,
    Passage,
    PassageCreate,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    Student,
    User,
    UserCreate,
)

_engine_override: object | None = None


def set_engine(engine_obj: object | None) -> None:
    """测试/CLI 用：覆盖全局 engine，所有从 core.db 取 engine 的路径都受影响。"""
    global _engine_override
    _engine_override = engine_obj


def _make_default_engine():
    # pool_pre_ping：PG 重启/连接被防火墙掐断后，借出前先探活，避免整批
    # "server closed the connection" 直到应用重启才恢复；
    # 池上限对齐「40 人班级齐交」的同步路由线程池峰值（默认 5+10 偏紧）
    return create_engine(
        str(settings.SQLALCHEMY_DATABASE_URI),
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


_default_engine = _make_default_engine()


def _get_engine():
    return _engine_override if _engine_override is not None else _default_engine


# 模块属性名保持 `engine`，get_db/worker/启动脚本均以 `from app.core.db import engine` 取值。
# 通过 __getattr__ 拦截，使得 deps 等模块级 `from ... import engine` 也能动态拿到覆盖后的引擎。
def __getattr__(name):
    if name == "engine":
        return _get_engine()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# 内置演示词表（PRD §7.4：学校没给 CSV 前先用公开分级词的子集，界面标明来源）
WORDLIST_NAME = "老词表（A2/B1/B2）已退役，仅保留历史统计"

# 2 天演示用自写短文（PRD §4：EIP 原文不进仓库，内容后换）
DEMO_PASSAGE_TEXT = (
    "Many students in our class have pets at home. "
    "Some prefer cats because they are quiet and independent. "
    "I prefer dogs. Dogs are friendly and loyal, and they always seem happy to see you. "
    "When I come home from school, my dog waits at the door and wags his tail. "
    "Playing with him outside helps me relax after a long day. "
    "Dogs need time and attention, but the joy they bring is worth the effort."
)

# 听后复述 3 句（由短到长，PRD §6：一轮 3 句）
DEMO_REPEAT_SENTENCES = [
    ("Dogs are friendly and loyal, and they always seem happy to see you.", 8),
    ("When I come home from school, my dog waits at the door and wags his tail.", 10),
    (
        "Dogs need time and attention, but the joy they bring to a family is worth the effort.",
        12,
    ),
]

# 情景问答种子：同主题（Pets）一组问法分属低/中/高档（PRD §8.4）
DEMO_SCENARIO_QUESTIONS = [
    ("A2", "Do you like cats or dogs? Why?", 15),
    ("A2", "What animals do you like? Tell me why.", 15),
    (
        "B1",
        "Some people say cats are easier to keep than dogs. What do you think? Give one reason.",
        30,
    ),
    ("B1", "Tell me about a pet you know. What is it like? Why do people like it?", 30),
    (
        "B1",
        "Many students want a pet but their parents say no. What can they say to their parents?",
        30,
    ),
    (
        "B2",
        "Some cities do not allow large dogs in small apartments. Do you think this rule is fair? Explain your view with reasons.",
        45,
    ),
    (
        "B2",
        "How do you think pets change a family's daily life? Give two examples.",
        45,
    ),
]

DEMO_CLASSROOM_CODE = "DEMO01"

SCHOOL_LIFE_TOPIC = "School Life"
SCHOOL_LIFE_QUESTIONS = [
    (
        "A2",
        "How do you get to school? What time do you arrive?",
        "你怎样去学校？几点到校？",
        20,
    ),
    (
        "A2",
        "What is your favourite school subject? Why do you like it?",
        "你最喜欢哪门学科？为什么喜欢它？",
        20,
    ),
    (
        "A2",
        "Where do you have lunch at school? What do you usually eat?",
        "你在学校哪里吃午饭？通常吃什么？",
        20,
    ),
    (
        "A2",
        "What do you do with your friends during the school break?",
        "课间休息时，你和朋友们一起做什么？",
        20,
    ),
    (
        "A2",
        "What do you usually do after school? Who do you do it with?",
        "放学后你通常做什么？和谁一起？",
        20,
    ),
    (
        "B1",
        "What do you enjoy most about school? Explain why and give an example.",
        "你最喜欢学校生活的哪一点？请说明原因并举一个例子。",
        40,
    ),
    (
        "B1",
        "Tell me about a school event you enjoyed. What happened, and why was it special for you?",
        "讲述一次你喜欢的学校活动。发生了什么？为什么这次活动对你很特别？",
        45,
    ),
    (
        "B1",
        "Do you prefer studying alone or with classmates? Compare the two and explain your choice.",
        "你更喜欢独自学习还是和同学一起学习？请比较两种方式并说明你的选择。",
        45,
    ),
    (
        "B1",
        "Your school wants to start a new club: a sports club, a music club or a reading club. Which would you suggest, and why?",
        "学校想新开一个社团：运动社、音乐社或阅读社。你会建议开哪一个？为什么？",
        45,
    ),
    (
        "B1",
        "If you could change one thing about your school day, what would it be? Explain how it would help students.",
        "如果能改变学校日常安排中的一件事，你会改变什么？请说明这会怎样帮助学生。",
        45,
    ),
]


# make sure all SQLModel models are imported (app.models) before initializing DB
# otherwise, SQLModel might fail to initialize relationships properly
# for more information: https://github.com/fastapi/full-stack-fastapi-template/issues/28


def _seed_practice_content(session: Session) -> None:
    from app.models import Unit

    unit = session.exec(select(Unit).limit(1)).first()
    if unit is None:
        unit = Unit(order_index=0, title="Unit 1 · Pets", topic="Pets")
        session.add(unit)
        session.commit()

    passage = session.exec(select(Passage).where(Passage.slug == "demo-pets")).first()
    if not passage:
        passage = crud.create_passage(
            session=session,
            passage_in=PassageCreate(
                slug="demo-pets",
                title="Why I Prefer Dogs",
                topic="Pets",
                cefr_band="B1",
                text=DEMO_PASSAGE_TEXT,
                suggested_seconds=45,
                unit_id=unit.id,
            ),
        )
    elif passage.unit_id is None:
        passage.unit_id = unit.id
        session.add(passage)
        session.commit()

    if not session.exec(
        select(RepeatSentence).where(RepeatSentence.passage_id == passage.id)
    ).first():
        for index, (text, seconds) in enumerate(DEMO_REPEAT_SENTENCES):
            session.add(
                RepeatSentence(
                    passage_id=passage.id,
                    order_index=index,
                    text=text,
                    suggested_seconds=seconds,
                )
            )
        session.commit()

    scenario = session.exec(select(Scenario).where(Scenario.topic == "Pets")).first()
    if not scenario:
        scenario = Scenario(topic="Pets")
        session.add(scenario)
        session.commit()
        for index, (band, text, seconds) in enumerate(DEMO_SCENARIO_QUESTIONS):
            session.add(
                ScenarioQuestion(
                    scenario_id=scenario.id,
                    band=band,
                    order_index=index,
                    text=text,
                    suggested_seconds=seconds,
                )
            )
        session.commit()

    demo_classroom = session.exec(
        select(Classroom).where(Classroom.code == DEMO_CLASSROOM_CODE)
    ).first()
    if demo_classroom is None:
        demo_classroom = Classroom(code=DEMO_CLASSROOM_CODE, class_size=40)
        session.add(demo_classroom)
        session.commit()

    # 本地演示学生账号（学号 student / 密码 demo1234），已加入 DEMO01
    if settings.ENVIRONMENT == "local" and demo_classroom is not None:
        from app.core.security import get_password_hash

        demo_student = session.exec(
            select(User).where(User.username == "student")  # type: ignore[arg-type]
        ).first()
        if demo_student is None:
            demo_student = User(
                username="student",
                full_name="演示学生",
                role="student",
                hashed_password=get_password_hash("demo1234"),
            )
            session.add(demo_student)
            session.commit()
        joined = session.exec(
            select(Student).where(
                Student.classroom_id == demo_classroom.id,  # type: ignore[arg-type]
                Student.user_id == demo_student.id,  # type: ignore[arg-type]
            )
        ).first()
        if joined is None:
            session.add(
                Student(
                    classroom_id=demo_classroom.id,
                    user_id=demo_student.id,
                    display_name="演示学生",
                )
            )
            session.commit()

    _seed_school_life_questions(session)
    _seed_vocabulary_demo(session)
    _seed_sentence_frames(session)


# 自写演示词条（词汇学习模块 P0）：与教材无关，学校 CSV 可在管理端覆盖。
# accepted_spellings 只收真正的拼写变体（如英美 favourite/favorite），不收同义词
# ——同义词会把没掌握目标词的答案误判为正确。
# (headword, part_of_speech, meaning_zh, meaning_en, accepted_spellings, example_en)
DEMO_VOCAB_WORDS: list[
    tuple[str, str, str, str | None, tuple[str, ...], str | None]
] = [
    (
        "dog",
        "n.",
        "狗",
        "a common animal that people keep as a pet",
        (),
        "My dog greets me at the door.",
    ),
    (
        "cat",
        "n.",
        "猫",
        "a small furry animal often kept as a pet",
        (),
        "The cat is sleeping on the sofa.",
    ),
    (
        "rabbit",
        "n.",
        "兔子",
        "a small animal with long ears",
        (),
        "The rabbit eats carrots.",
    ),
    (
        "parrot",
        "n.",
        "鹦鹉",
        "a bird that can copy human speech",
        (),
        "Our parrot says hello every morning.",
    ),
    (
        "friendly",
        "adj.",
        "友好的",
        "kind and pleasant to others",
        (),
        "She is friendly to new classmates.",
    ),
    (
        "gentle",
        "adj.",
        "温柔的",
        "calm and kind, not rough",
        (),
        "The panda is a gentle animal.",
    ),
    (
        "clever",
        "adj.",
        "聪明的",
        "quick at learning and understanding",
        (),
        "Crows are clever birds.",
    ),
    (
        "feed",
        "v.",
        "喂食",
        "to give food to a person or animal",
        (),
        "I feed my cat twice a day.",
    ),
    (
        "borrow",
        "v.",
        "借入",
        "to take something and return it later",
        (),
        "May I borrow your pen?",
    ),
    (
        "library",
        "n.",
        "图书馆",
        "a place where you can read and borrow books",
        (),
        "We study in the library after class.",
    ),
    (
        "timetable",
        "n.",
        "课程表",
        "a plan that shows the times of classes",
        (),
        "Check the timetable before you go.",
    ),
    (
        "homework",
        "n.",
        "作业",
        "schoolwork you do at home",
        (),
        "I finish my homework before dinner.",
    ),
    (
        "practice",
        "n.",
        "练习",
        "repeated exercise to improve a skill",
        (),
        "Practice makes progress.",
    ),
    (
        "careful",
        "adj.",
        "仔细的",
        "paying attention to avoid mistakes",
        (),
        "Be careful with the glass.",
    ),
    (
        "healthy",
        "adj.",
        "健康的",
        "physically strong and not ill",
        (),
        "Fresh fruit keeps us healthy.",
    ),
    (
        "delicious",
        "adj.",
        "美味的",
        "tasting very good",
        (),
        "The dumplings are delicious.",
    ),
    (
        "weather",
        "n.",
        "天气",
        "the conditions outside, like sun or rain",
        (),
        "The weather is sunny today.",
    ),
    (
        "umbrella",
        "n.",
        "雨伞",
        "a thing you hold to keep off rain",
        (),
        "Take an umbrella in case it rains.",
    ),
    (
        "weekend",
        "n.",
        "周末",
        "Saturday and Sunday",
        (),
        "We visit my grandparents on the weekend.",
    ),
    (
        "favorite",
        "adj.",
        "最喜欢的",
        "liked more than all others",
        ("favourite",),
        "Blue is my favorite color.",
    ),
]


def _seed_vocabulary_demo(session: Session) -> None:
    """公共演示词库（20 个自写词条）：已存在任何词库时不重复种入。"""
    from app.models import (
        VocabularyBook,
        VocabularyBookItem,
        VocabularyWord,
    )

    if session.exec(select(VocabularyBook).limit(1)).first() is not None:
        return
    book = VocabularyBook(
        title="演示词库 · Pets & School",
        description="自写演示词条（20 词），供词汇任务发布试用；学校词库可在管理端导入替换。",
        scope="public",
    )
    session.add(book)
    session.flush()
    for position, (
        headword,
        pos,
        meaning_zh,
        meaning_en,
        accepted,
        example,
    ) in enumerate(DEMO_VOCAB_WORDS, start=1):
        word = VocabularyWord(
            headword=headword,
            part_of_speech=pos,
            meaning_zh=meaning_zh,
            meaning_en=meaning_en,
            accepted_spellings=list(accepted) or None,
            example_en=example,
        )
        session.add(word)
        session.flush()
        session.add(
            VocabularyBookItem(book_id=book.id, word_id=word.id, position=position)
        )
    session.commit()


def _seed_school_life_questions(session: Session) -> None:
    # 已有主题由老师维护，初始化不覆盖编辑，也不恢复已删除的题目。
    if session.exec(
        select(Scenario).where(Scenario.topic == SCHOOL_LIFE_TOPIC)
    ).first():
        return

    scenario = Scenario(topic=SCHOOL_LIFE_TOPIC)
    session.add(scenario)
    session.flush()
    for index, (band, text, translation, seconds) in enumerate(SCHOOL_LIFE_QUESTIONS):
        session.add(
            ScenarioQuestion(
                scenario_id=scenario.id,
                band=band,
                order_index=index,
                text=text,
                translation=translation,
                suggested_seconds=seconds,
            )
        )
    session.commit()


# 内置示例句型（分级题型训练 PR B）：仅句型表为空时种入，学校可自行增删。
# 覆盖常见表达用途与 KET/PET/IELTS 级别；KET/PET 为课堂版（语言更简单）。
DEMO_SENTENCE_FRAMES: list[tuple[str, str, str | None, str, str]] = [
    # (level, purpose, exam_kind, text_en, text_zh)
    ("KET", "opinion", None, "I think ... is really fun.", "我觉得……很有意思。"),
    ("KET", "describe", None, "My ... is small and cute.", "我的……很小很可爱。"),
    ("KET", "past", None, "Last weekend, I went to ...", "上周末我去了……"),
    (
        "PET",
        "opinion",
        None,
        "In my opinion, ... is worth trying.",
        "在我看来，……值得一试。",
    ),
    ("PET", "reason", None, "The main reason is that ...", "主要原因是……"),
    ("PET", "past", "ielts_p1", "I remember when I first ...", "我记得我第一次……"),
    (
        "ACADEMIC",
        "compare",
        "ielts_p3",
        "Compared with ..., ... is more ...",
        "与……相比，……更……",
    ),
    ("ACADEMIC", "example", "ielts_p2", "Take ... as an example, ...", "以……为例，……"),
    ("CET4", "opinion", None, "From my perspective, ...", "从我的角度来看，……"),
    ("CET4", "future", "toefl_lnr", "In the future, I plan to ...", "将来我打算……"),
    ("IELTS_TOEFL", "speculate", "ielts_p3", "It is possible that ...", "有可能……"),
    (
        "IELTS_TOEFL",
        "compare",
        "toefl_lnr",
        "There is a sharp contrast between ... and ...",
        "……与……形成鲜明对比。",
    ),
]


def _seed_sentence_frames(session: Session) -> None:
    from app.models import SentenceFrame

    if session.exec(select(SentenceFrame).limit(1)).first() is not None:
        return
    for level, purpose, exam_kind, text_en, text_zh in DEMO_SENTENCE_FRAMES:
        session.add(
            SentenceFrame(
                level=level,
                purpose=purpose,
                exam_kind=exam_kind,
                text_en=text_en,
                text_zh=text_zh,
            )
        )
    session.commit()


def init_db(session: Session) -> None:
    # Tables should be created with Alembic migrations
    # But if you don't want to use migrations, create
    # the tables un-commenting the next lines
    # from sqlmodel import SQLModel

    # This works because the models are already imported and registered from app.models
    # SQLModel.metadata.create_all(engine)

    user = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        user = crud.create_user(session=session, user_create=user_in)

    _seed_practice_content(session)
