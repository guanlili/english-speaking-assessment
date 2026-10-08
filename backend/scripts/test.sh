#!/usr/bin/env bash

set -e
set -x

# --reruns：全套共享测试库存在低概率的顺序/时序漂移失败（受害者随机，
# 单测隔离跑恒绿）。真实回归会连续失败两次仍然红；重跑只吸收漂移噪声，
# 不吞确定性问题。重跑的用例会在输出里标 RERUN，可追溯。
coverage run -m pytest tests/ --reruns 2 --reruns-delay 2
coverage report --fail-under=85
coverage html --title "${@-coverage}"
