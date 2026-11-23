@echo off
REM 비교 화면 실행 (Anaconda Python 3.11 사용)
cd /d "%~dp0"
set PY=D:\ananconda3\python.exe
if not exist "%PY%" (
  echo [오류] %PY% 를 찾을 수 없습니다. run.bat 안의 PY 경로를 고쳐 주세요.
  pause
  exit /b 1
)
"%PY%" -m streamlit --version >nul 2>&1 || "%PY%" -m pip install -r requirements.txt
"%PY%" -m streamlit run app.py
pause
