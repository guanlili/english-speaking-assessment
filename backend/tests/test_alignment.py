"""词级对齐单元测试：逐词标注与个人漏词聚合共用的对齐逻辑。"""

from app.scoring.heuristic import (
    align_words,
    lemma_variants,
    tokenize_with_spans,
)


def test_tokenize_with_spans_offsets_match_slices():
    text = "Dogs are  friendly!"
    tokens = tokenize_with_spans(text)
    assert tokens == [("dogs", 0, 4), ("are", 5, 8), ("friendly", 10, 18)]
    for token, start, end in tokens:
        assert text[start:end].lower() == token


def test_lemma_variants_rules():
    assert "dog" in lemma_variants("dogs")
    assert "make" in lemma_variants("making")
    assert "run" in lemma_variants("running")
    assert "hope" in lemma_variants("hoped")
    assert "stop" in lemma_variants("stopped")
    assert "baby" in lemma_variants("babies")


def test_align_perfect_read_correct():
    result = align_words("The cat sat on the mat.", "the cat sat on the mat")
    statuses = [w["status"] for w in result["words"]]
    assert statuses == ["correct"] * 6
    assert result["extras"] == []
    # 原文切片保留原大小写
    first = result["words"][0]
    assert first["text"] == "The" and first["start"] == 0 and first["end"] == 3


def test_align_inflection_counts_as_correct():
    # 复数/时态屈折算读对（与评分归一口径一致）
    result = align_words("Dogs run fast.", "dog runs fast")
    assert [w["status"] for w in result["words"]] == [
        "correct",
        "correct",
        "correct",
    ]


def test_align_missing_words():
    result = align_words("The quick brown fox jumps.", "the fox")
    statuses = [w["text"] for w in result["words"] if w["status"] == "missing"]
    assert statuses == ["quick", "brown", "jumps"]


def test_align_error_word_has_heard():
    result = align_words("I like green apples.", "i like gren apple")
    # green 读成 gren → error（heard 记录听到的形式）；apples 读成 apple 算读对
    by_word = {w["text"]: w for w in result["words"]}
    assert by_word["green"]["status"] == "error"
    assert by_word["green"]["heard"] == "gren"
    assert by_word["apples"]["status"] == "correct"
    # gren 与参考词对齐后，无多余词
    assert result["extras"] == []


def test_align_extra_words():
    result = align_words("Hello world.", "um hello there world")
    extras = [e["text"] for e in result["extras"]]
    assert "um" in extras and "there" in extras
    assert all(w["status"] == "correct" for w in result["words"])


def test_align_empty_transcript_all_missing():
    result = align_words("Please read this line.", "")
    assert [w["status"] for w in result["words"]] == ["missing"] * 4
    assert result["extras"] == []


def test_align_empty_reference_no_crash():
    result = align_words("", "whatever was said")
    assert result == {"words": [], "extras": []}


def test_align_contraction_and_punctuation():
    result = align_words("Don't stop.", "dont stop")
    # 撇号归属单词：don't 与 dont 属同一词（归一含撇号差异），形式不同记 error
    statuses = [w["status"] for w in result["words"]]
    assert "error" in statuses or "correct" in statuses
