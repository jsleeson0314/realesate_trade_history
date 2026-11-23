@echo off
REM 비교 화면 실행. 처음 한 번은 이 폴더 전용 파이썬 환경(.venv)을 만들고 패키지를 설치합니다.
REM 이렇게 하면 Anaconda 기본 환경의 패키지는 건드리지 않습니다.
cd /d "%~dp0"
set BASEPY=D:\ananconda3\python.exe
if not exist ".venv\Scripts\python.exe" (
  if not exist "%BASEPY%" (
    echo [오류] %BASEPY% 를 찾을 수 없습니다. run.bat 안의 BASEPY 경로를 고쳐 주세요.
    pause
    exit /b 1
  )
  echo 전용 환경을 만드는 중입니다. 처음 한 번만 몇 분 걸립니다...
  "%BASEPY%" -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" -m streamlit run app.py
pause
