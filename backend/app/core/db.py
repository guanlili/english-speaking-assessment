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
    WordlistEntry,
)

_engine_override: object | None = None


def set_engine(engine_obj: object | None) -> None:
    """测试/CLI 用：覆盖全局 engine，所有从 core.db 取 engine 的路径都受影响。"""
    global _engine_override
    _engine_override = engine_obj


def _make_default_engine():
    return create_engine(str(settings.SQLALCHEMY_DATABASE_URI))


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
WORDLIST_NAME = "内置演示词表（待学校分级词表 CSV 替换）"

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
    _seed_wordlist(session)
    _seed_vocabulary_demo(session)


# 自写演示词条（词汇学习模块 P0）：与教材无关，学校 CSV 可在管理端覆盖。
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
        ("bunny",),
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
        ("smart",),
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
        ("schedule",),
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
        ("yummy",),
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


_WORDLIST_A2 = """
animal answer apple baby ball beautiful because bed before begin best better
bird book box bread breakfast busy buy call car cheap child city clean clothes
color cook cool country dance delicious dinner dirty doctor dog easy enjoy
every expensive far fast favorite feel fine fish food foot free fresh friend
fun funny game garden girl glad great hair half hand happy hard head healthy
hear heavy high holiday home homework hope horse hour hungry idea important
interesting joke keep kind kitchen know lake last late laugh learn leave light
listen long look love lunch make many market meal meet milk minute money
month moon morning mother mountain mouth move music name near never nice night
often old open orange outside park party people person pet piano picture place
plan play please police poor popular practice pretty problem quick quiet rain
read ready real remember rest rice rich right river room round run safe say
school sea season seat see sell share shirt shoe shop short show sing sister
sit sleep slow small smile snow song soon sorry sound south speak sport spring
stand start stay stop store story street strong study summer sun sweet swim
table talk teach teacher tell thank thin thing think thirsty tired today
together tomorrow town train travel tree trip under use useful vegetable very
visit voice wait wake walk want warm wash watch water way wear weather week
welcome wet what wheel white wide wind window winter wish woman word work
world write year yellow yesterday young zoo
"""

_WORDLIST_B1 = """
ability accept accident achieve active actually advice afford agreement allow
alone although amazing announce annoy anxious apply argue arrange artist
attempt attend available average avoid award aware balance belong benefit
blame brave breath brief calm cancel cause celebrate certain chance charge
choice communicate community compare compete complain concentrate confidence
confirm connect consider contain convenient convince corner couple courage
crazy create crowd curious damage decide defend degree deliver depend describe
design desire destroy develop diet difference difficult disappoint discover
discuss disease distance divide double doubt draw dream drop eager encourage
effort emotion energetic escape especially event exact examine excellent exist
expect experience experiment explain explore express extremely failure
familiar famous fault fear figure final focus foreign forget forgive fortune
freedom frequent generous gentle genuine goal grateful habit handle harm hate
hesitate honest huge humor imagine immediately impress improve independent
individual influence inform insist inspire instant instead intend interest
interrupt introduce invent invite involve journey judge kindness lack launch
lazy leader lonely loyal luck main manage manner meanwhile measure mention
message mind modest moment mood mostly motivate mystery narrow nation natural
necessary negative nervous normal notice nowhere obvious occasion offer
operate opinion opportunity organize outcome overcome pain particular passion
patient peace perform perhaps period permit personal persuade physical plain
pleasure plenty polite positive possibility postpone potential praise prefer
prepare present pressure pretend prevent pride private process progress
promise proper protect proud prove provide public punish purpose pursue
quality quantity quit rare rate realize reason recall recognize recommend
reduce refuse regret regular relate relax release rely remain remind remote
repair repeat replace reply require rescue research respect responsible
result return reveal reward rise risk role rough routine rude rush sacrifice
safety satisfy scene simple skill smart solve suffer suggest support suppose
survive task technique technology tendency thick threaten tiny tool tourist
treat trust unlike usual various victim violence virtue warn waste weak
wealthy weird willing wise wonder worried
"""

_WORDLIST_B2 = """
abandon accurate adequate adjust admire adopt advocate ambitious anticipate
apparent appeal approach appropriate aspect assess assume assure attitude
attribute authentic authority automatic await bias blend boost brilliant
campaign capable capacity channel chaos coherent commit compel compensate
competent complex comply compose comprehensive comprise compromise concede
conclude conflict consent considerable consistent constitute consult contest
contradict credible crucial cultivate curb decline dedicate deliberate depict
deprive deserve desirable desperate devise devote diminish discipline dispute
distinct distort diverse domain dominate drastic dwell elaborate eliminate
embrace endeavor endure enforce enhance enquire ensure entitle equivalent
erode essential establish esteem ethic evaluate evoke exceed exclusive
execute exhaust exhibit expand expertise explicit expose extensive facilitate
feasible flaw flourish foundation framework halt hazard highlight hostile
hypothesis illustrate immerse impair imperative implement implication
implicit incentive incline inevitable infer inherent inhibit initiate
innovative insight intact integral intense intimate intricate intrinsic invoke
irrelevant legitimate leverage likewise maintain manipulate mediate
meticulous mitigate modify monitor negotiate notable notion nurture obscure
obsolete obstacle optimistic originate overwhelm paradox parallel perceive
plausible portray precede precise predominant preliminary prerequisite
preserve prevail profound reconcile refine regulate reinforce reluctant render
reputation reside resolve restore restrain retain retrieve reverse rigid robust
rural scrutiny secure sequence shallow shrink significant simultaneous
skeptical sole sophisticated specify stance strive substantial subtle suffice
summon superficial surplus sustain tangible tedious terminate thorough
tolerate trait transition tremendous trivial turbulent ultimate undermine
undertake utilize vague vast verge vigorous virtual vivid vulnerable
widespread yield
"""


def _seed_wordlist(session: Session) -> None:
    if session.exec(select(WordlistEntry).limit(1)).first() is not None:
        return
    for band, blob in (
        ("A2", _WORDLIST_A2),
        ("B1", _WORDLIST_B1),
        ("B2", _WORDLIST_B2),
    ):
        for lemma in sorted(set(blob.split())):
            session.add(WordlistEntry(lemma=lemma, band=band))
    session.commit()
