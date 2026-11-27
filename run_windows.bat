@echo off
REM RFL OMS 실행 (Windows). Python 3.10 이상 필요.
cd /d "%~dp0"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
streamlit run app.py
