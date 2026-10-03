"""把提取产物 output/<level>.json 转成管理端可导入的 CSV（保留核对状态与来源）。

管理端「五级词库」导入支持可选列 needs_review / sources / note：
    headword,part_of_speech,meaning_zh,needs_review,sources,note

PET 等 OCR 产物的 needs_review 全为 true、sources 带分节标签，
导入后行为与提取工具一致：未核对行不参与两模块统计。

用法（backend/ 目录）：
    python scripts/vocab_level_import/to_import_csv.py --level pet
        → output/pet.import.csv
"""

import argparse
import csv
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent / "output"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--level", required=True, help="KET/PET/ACADEMIC/CET4/IELTS_TOEFL"
    )
    args = parser.parse_args()

    source = OUTPUT_DIR / f"{args.level.lower()}.json"
    rows = json.loads(source.read_text(encoding="utf-8"))
    target = OUTPUT_DIR / f"{args.level.lower()}.import.csv"
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "headword",
                "part_of_speech",
                "meaning_zh",
                "needs_review",
                "sources",
                "note",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["headword"],
                    row.get("part_of_speech") or "",
                    row.get("meaning_zh") or "",
                    "true" if row.get("needs_review") else "false",
                    ";".join(row.get("sources") or []),
                    row.get("note") or "",
                ]
            )
    reviewed = sum(1 for row in rows if not row.get("needs_review"))
    logger.info("已生成 %s（%s 行，其中已核对 %s 行）", target, len(rows), reviewed)


if __name__ == "__main__":
    main()
