#!/usr/bin/env bash

set -e
set -x

coverage run -m pytest tests/
coverage report --fail-under=85
coverage html --title "${@-coverage}"
