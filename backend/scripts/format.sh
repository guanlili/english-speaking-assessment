#!/bin/sh -e
set -x

# 与 lint.sh / verify.sh 同口径：应用代码、测试代码、脚本一起格式化。
# 此前只覆盖 app scripts，tests 里的新文件永远过不了 verify.sh 的格式闸。
ruff check app tests scripts --fix
ruff format app tests scripts
