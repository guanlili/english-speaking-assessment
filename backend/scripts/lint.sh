#!/usr/bin/env bash

set -e
set -x

# 质量检查覆盖应用代码与测试代码（tests 与 app 同一标准）
ty check app tests
ruff check app tests
ruff format app tests --check

# scripts/ 里只有 perf_baseline.py 进 lint：它是唯一要长期跑对的守卫脚本
# （查询数回归门禁），它自己失真整个门禁就没意义。其余 scripts/ 是已完成
# 使命的一次性导入/运维工具，纳入 lint 等于把「历史遗留」升级成「必须持续
# 维护」，收益为负——它们的未用变量可能是当年漏掉的逻辑，需要单独判断。
ruff check scripts/perf_baseline.py
ruff format scripts/perf_baseline.py --check
