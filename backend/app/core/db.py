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
    User,
    UserCreate,
    WordlistEntry,
)

engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))

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


# make sure all SQLModel models are imported (app.models) before initializing DB
# otherwise, SQLModel might fail to initialize relationships properly
# for more information: https://github.com/fastapi/full-stack-fastapi-template/issues/28


def _seed_practice_content(session: Session) -> None:
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
            ),
        )

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

    if not session.exec(
        select(Classroom).where(Classroom.code == DEMO_CLASSROOM_CODE)
    ).first():
        session.add(Classroom(code=DEMO_CLASSROOM_CODE, class_size=40))
        session.commit()

    _seed_wordlist(session)


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
