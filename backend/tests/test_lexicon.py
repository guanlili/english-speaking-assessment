"""词表命中分析（LexiconScorer）单元测试（PRD US-07 验收口径）。"""

from app.scoring.lexicon import STABLE_BAND_HITS, analyze_transcript


def _wordlists(**overrides: set[str]) -> dict[str, set[str]]:
    base = {
        "A2": {"dog", "cat", "like", "home", "happy", "friend", "play", "food"},
        "B1": {"prefer", "loyal", "independent", "relax", "effort", "habit"},
        "B2": {"crucial", "significant", "overwhelm", "advocate", "insight"},
    }
    base.update(overrides)
    return base


def test_empty_transcript_or_wordlist() -> None:
    assert analyze_transcript("", _wordlists()).cefr_label is None
    empty = {"A2": set(), "B1": set(), "B2": set()}
    assert analyze_transcript("i like dogs", empty).cefr_label is None


def test_inflected_forms_match_lemma() -> None:
    analysis = analyze_transcript(
        "I like dogs and cats; they are making me happy, I preferred playing",
        _wordlists(),
    )
    all_hits = [w for words in analysis.hits_by_band.values() for w in words]
    assert "dogs" in all_hits  # 复数 → dog
    assert "cats" in all_hits  # 复数 → cat
    assert "playing" in all_hits  # 进行时 → play
    assert "preferred" in all_hits  # 过去式 → prefer
    assert "making" not in all_hits  # make 不在词表，不该命中


def test_repeat_reference_words_not_special() -> None:
    """词汇分析只看传入的转写文本本身（路由层只对问答调用），词表命按最高档归类。"""
    analysis = analyze_transcript("loyal loyal loyal loyal loyal loyal", _wordlists())
    assert analysis.hits_by_band["B1"] == ["loyal"]


def test_stable_band_label_rule() -> None:
    """US-07 验收：5 个以上 B1 词且几乎没有 B2 → B1。"""
    b1_words = "prefer loyal independent relax effort habit"
    analysis = analyze_transcript(f"{b1_words} and some dogs at home", _wordlists())
    assert len(analysis.hits_by_band["B1"]) >= STABLE_BAND_HITS
    assert analysis.cefr_label == "B1"


def test_few_b1_hits_downgrades() -> None:
    """B1 命中不足 5 个（且无更高档）→ 降为 A2。"""
    analysis = analyze_transcript("i prefer loyal dogs", _wordlists())
    assert analysis.hits_by_band["B1"] == ["loyal", "prefer"]
    assert analysis.cefr_label == "A2"


def test_no_hits_defaults_a2() -> None:
    analysis = analyze_transcript("xylophone quizzical", _wordlists())
    assert analysis.cefr_label == "A2"
    assert analysis.coverage_ratio == 0.0


def test_coverage_ratio() -> None:
    """覆盖比例 = 命中词数（去重）/ 转写去重词数。"""
    analysis = analyze_transcript("dogs cats unknownword", _wordlists())
    assert analysis.coverage_ratio == round(2 / 3, 2)


def test_word_counts_once_at_highest_band() -> None:
    """同一词形只按最高档计一次。"""
    wordlists = _wordlists(A2={"loyal", "dog"}, B1={"loyal"})
    analysis = analyze_transcript("loyal dog", wordlists)
    assert analysis.hits_by_band["B1"] == ["loyal"]
    assert analysis.hits_by_band["A2"] == ["dog"]
