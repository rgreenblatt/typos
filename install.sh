#!/bin/bash
set -e

cd "$(dirname "$0")"

python3 -m venv .venv
.venv/bin/pip install anthropic
