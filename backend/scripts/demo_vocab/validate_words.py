"""本地演示词表数据校验脚本（纯标准库，可重复运行）。

校验对象：同目录 ``words.json``。

检查项：
- 顶层 demo / license_owner / license_ref / note 标记齐全；
- 总词条数 220，五级（KET / PET / ACADEMIC / CET4 / IELTS_TOEFL）各 44；
- headword 唯一、为单个英文单词（不含空格/短语）；
- 例句包含 headword 原形（大小写不敏感，按词边界匹配）；
- morphology 各段按顺序拼接严格等于 headword，kind ∈ prefix/root/suffix；
- 每条 source_type == "demo"、review_status == "approved"；
- 至少 80 个词条有 2 段及以上真实词法拆解。

用法（仓库根目录或任意目录均可）::

    python3 backend/scripts/demo_vocab/validate_words.py

退出码：0 = 全部通过；1 = 存在校验错误（错误明细打印到 stderr/stdout）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LEVELS = ["KET", "PET", "ACADEMIC", "CET4", "IELTS_TOEFL"]
EXPECTED_TOTAL = 220
EXPECTED_PER_LEVEL = 44
MIN_MULTI_SEGMENT = 80
VALID_KINDS = {"prefix", "root", "suffix"}
REQUIRED_WORD_FIELDS = (
    "headword",
    "level",
    "part_of_speech",
    "meaning_zh",
    "meaning_en",
    "example_en",
    "morphology",
)

WORDS_FILE = Path(__file__).resolve().parent / "words.json"


def _check(payload: dict) -> tuple[list[str], dict]:
    errors: list[str] = []

    # ── 顶层 demo / 授权标记 ──────────────────────────────────────
    if payload.get("demo") is not True:
        errors.append("顶层字段 demo 必须为 true")
    if payload.get("license_owner") != "Demo Content Team":
        errors.append('顶层字段 license_owner 必须为 "Demo Content Team"')
    if payload.get("license_ref") != "DEMO-ONLY":
        errors.append('顶层字段 license_ref 必须为 "DEMO-ONLY"')
    note = str(payload.get("note", ""))
    if "not for production" not in note:
        errors.append("顶层字段 note 必须声明仅本地演示、不用于生产")

    words = payload.get("words")
    if not isinstance(words, list):
        errors.append("words 必须为数组")
        return errors, {}

    seen: set[str] = set()
    level_counts: dict[str, int] = dict.fromkeys(LEVELS, 0)
    multi_segment = 0

    for index, word in enumerate(words):
        prefix = f"words[{index}]"

        if not isinstance(word, dict):
            errors.append(f"{prefix}: 条目必须为对象")
            continue

        missing = [f for f in REQUIRED_WORD_FIELDS if not word.get(f)]
        if missing:
            errors.append(f"{prefix}: 缺少或为空字段 {missing}")
            continue

        headword = str(word["headword"]).strip()
        level = str(word["level"]).strip()

        if level not in LEVELS:
            errors.append(f"{prefix} [{headword}]: 非法 level={level!r}")
        else:
            level_counts[level] += 1

        if not headword or not headword.isalpha():
            errors.append(f"{prefix}: headword 必须为单个英文单词，收到 {headword!r}")
        elif headword in seen:
            errors.append(f"{prefix}: headword 重复 {headword!r}")
        else:
            seen.add(headword)

        if word.get("source_type") != "demo":
            errors.append(f'{prefix} [{headword}]: source_type 必须为 "demo"')
        if word.get("review_status") != "approved":
            errors.append(f'{prefix} [{headword}]: review_status 必须为 "approved"')

        example = str(word["example_en"])
        pattern = re.compile(r"\b" + re.escape(headword) + r"\b", re.IGNORECASE)
        if not pattern.search(example):
            errors.append(
                f"{prefix} [{headword}]: 例句未包含 headword 原形 → {example!r}"
            )

        morphology = word["morphology"]
        if not isinstance(morphology, list) or not morphology:
            errors.append(f"{prefix} [{headword}]: morphology 至少 1 段")
            continue

        concat = ""
        for seg_index, seg in enumerate(morphology):
            if not isinstance(seg, dict):
                errors.append(f"{prefix} [{headword}] seg[{seg_index}]: 必须为对象")
                continue
            text = str(seg.get("text", ""))
            gloss = str(seg.get("gloss", ""))
            kind = str(seg.get("kind", ""))
            if not text or not gloss:
                errors.append(
                    f"{prefix} [{headword}] seg[{seg_index}]: text/gloss 不能为空"
                )
            if kind not in VALID_KINDS:
                errors.append(
                    f"{prefix} [{headword}] seg[{seg_index}]: 非法 kind={kind!r}"
                )
            concat += text

        if concat != headword:
            errors.append(
                f"{prefix} [{headword}]: morphology 拼接 {concat!r} != headword"
            )
        if len(morphology) >= 2:
            multi_segment += 1

    # ── 总量与分级统计 ───────────────────────────────────────────
    total = len(words)
    if total != EXPECTED_TOTAL:
        errors.append(f"词条总数 {total}，预期 {EXPECTED_TOTAL}")
    for lv in LEVELS:
        count = level_counts.get(lv, 0)
        if count != EXPECTED_PER_LEVEL:
            errors.append(f"级别 {lv} 词条数 {count}，预期 {EXPECTED_PER_LEVEL}")
    if multi_segment < MIN_MULTI_SEGMENT:
        errors.append(f"多段拆解词条 {multi_segment}，至少需要 {MIN_MULTI_SEGMENT}")

    stats = {
        "total": total,
        "level_counts": level_counts,
        "unique_headwords": len(seen),
        "multi_segment": multi_segment,
    }
    return errors, stats


def main() -> int:
    if not WORDS_FILE.exists():
        print(f"❌ 找不到数据文件: {WORDS_FILE}", file=sys.stderr)
        return 1

    payload = json.loads(WORDS_FILE.read_text(encoding="utf-8"))
    errors, stats = _check(payload)

    print(f"数据文件: {WORDS_FILE}")
    print(
        "词条总数: {total}（预期 {expected}）".format(
            total=stats.get("total", 0), expected=EXPECTED_TOTAL
        )
    )
    print("分级统计:")
    for lv in LEVELS:
        print(f"  - {lv}: {stats.get('level_counts', {}).get(lv, 0)}")
    print(f"唯一 headword: {stats.get('unique_headwords', 0)}")
    print(f"两段及以上拆解: {stats.get('multi_segment', 0)}")

    if errors:
        print(f"\n❌ 校验失败，共 {len(errors)} 处问题：")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(
        "\n✅ 全部校验通过：220 条、五级各 44、例句含原形、词法拼接一致、demo 标记齐全。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
