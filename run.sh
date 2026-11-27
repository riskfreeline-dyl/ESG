#!/usr/bin/env bash
# RFL OMS 실행 (macOS / Linux). Python 3.10 이상 필요.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
pip install -q -r requirements.txt
streamlit run app.py
