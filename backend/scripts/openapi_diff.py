"""openapi 基线比对：路由/契约零漂移校验。

文本 diff 会因字典序、缩进、浮点格式报一堆假差异，所以这里做 JSON 结构化
遍历——键集合、类型、列表长度、标量值逐项对齐，只报真变化。

用法：
    python scripts/openapi_diff.py            # 与基线比对，有差异则退出码 1
    python scripts/openapi_diff.py --update   # 用当前 spec 重写基线
"""

from __future__ import annotations

import json
import pathlib
import sys

BASELINE = pathlib.Path(__file__).resolve().parent.parent / "openapi-baseline.json"


def _spec() -> dict:
    from app.main import app

    return app.openapi()


def _walk(a: object, b: object, path: str, out: list[str]) -> None:
    if type(a) is not type(b):
        out.append(f"{path}: 类型 {type(a).__name__} → {type(b).__name__}")
        return
    if isinstance(a, dict) and isinstance(b, dict):
        extra, missing = set(b) - set(a), set(a) - set(b)
        if extra:
            out.append(f"{path}: 新增键 {sorted(extra)}")
        if missing:
            out.append(f"{path}: 删除键 {sorted(missing)}")
        for key in sorted(set(a) & set(b)):
            _walk(a[key], b[key], f"{path}.{key}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: 长度 {len(a)} → {len(b)}")
        for idx in range(min(len(a), len(b))):
            _walk(a[idx], b[idx], f"{path}[{idx}]", out)
    elif a != b:
        out.append(f"{path}: {a!r} → {b!r}")


def main() -> int:
    spec = _spec()
    paths = len(spec.get("paths", {}))
    schemas = len(spec.get("components", {}).get("schemas", {}))

    if "--update" in sys.argv:
        BASELINE.write_text(
            json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        print(f"✅ 基线已更新：{paths} 路径 / {schemas} schemas → {BASELINE.name}")
        return 0

    if not BASELINE.exists():
        print(
            f"⚠️  没有基线（{BASELINE.name}）。当前 {paths} 路径 / {schemas} schemas。"
        )
        print("    确认无误后执行：python scripts/openapi_diff.py --update")
        return 1

    base = json.loads(BASELINE.read_text())
    diffs: list[str] = []
    _walk(base, spec, "$", diffs)

    if not diffs:
        print(f"✅ openapi 零漂移（{paths} 路径 / {schemas} schemas）")
        return 0

    print(
        f"❌ openapi 与基线有 {len(diffs)} 处差异（{paths} 路径 / {schemas} schemas）："
    )
    for line in diffs[:40]:
        print(f"   {line}")
    if len(diffs) > 40:
        print(f"   …还有 {len(diffs) - 40} 处")
    print()
    print("   这是有意的路由变更 → bash scripts/verify.sh --openapi-update")
    print("   这是意外漂移 → 回退改动，别更新基线")
    return 1


if __name__ == "__main__":
    sys.exit(main())
