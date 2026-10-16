"""全班薄弱点：转写对齐，不依赖数据库。"""

import uuid

from app.services.class_gaps import (
    aggregate_low_items,
    aggregate_word_gaps,
    missed_content_words,
)


def test_missed_content_words_skip_function_words_and_order() -> None:
    missed = missed_content_words(
        "I usually feed the cat",
        "I feed the cat",
    )
    assert missed == ["usually"]


def test_word_gaps_need_two_students_when_class_has_two() -> None:
    ada = uuid.uuid4()
    ben = uuid.uuid4()
    gaps = aggregate_word_gaps(
        [
            (ada, "I usually feed the cat", "I feed the cat"),
            (ben, "I usually feed the cat", "I usually feed the cat"),
            (ada, "The garden is quiet", "garden is quiet"),
        ]
    )
    # 只有 Ada 漏了 usually，两人都交过卷，不应上榜
    assert gaps == []


def test_word_gaps_rank_shared_misses() -> None:
    ada = uuid.uuid4()
    ben = uuid.uuid4()
    gaps = aggregate_word_gaps(
        [
            (ada, "I usually visit the museum", "I visit the museum"),
            (ben, "We usually visit the museum", "We visit museum"),
        ]
    )
    assert ("usually", 2) in gaps
    assert ("museum", 1) not in gaps


def test_single_student_still_sees_their_gap() -> None:
    ada = uuid.uuid4()
    gaps = aggregate_word_gaps([(ada, "Please describe your weekend", "describe")])
    assert ("weekend", 1) in gaps
    assert ("please", 1) in gaps


def test_low_items_hide_a_strong_class() -> None:
    student = uuid.uuid4()
    item = uuid.uuid4()
    assert aggregate_low_items([(student, item, "repeat", "Hello there", 92)]) == []


def test_low_items_surface_the_weakest_question() -> None:
    ada = uuid.uuid4()
    ben = uuid.uuid4()
    weak = uuid.uuid4()
    strong = uuid.uuid4()
    items = aggregate_low_items(
        [
            (ada, weak, "question", "Describe a pet", 55),
            (ben, weak, "question", "Describe a pet", 62),
            (ada, strong, "repeat", "I like cats", 90),
            (ben, strong, "repeat", "I like cats", 88),
        ]
    )
    assert len(items) == 1
    assert items[0]["item_id"] == weak
    assert items[0]["low_count"] == 2
    assert items[0]["avg_overall"] == 58.5
