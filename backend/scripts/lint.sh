#!/usr/bin/env bash

set -e
set -x

# 质量检查覆盖应用代码与测试代码（tests 与 app 同一标准）
ty check app tests
ruff check app tests
ruff format app tests --check
