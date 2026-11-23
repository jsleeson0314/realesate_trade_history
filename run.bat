@echo off
REM 아파트 실거래가 비교 화면 열기
REM - 처음 한 번은 이 폴더 전용 파이썬 환경(.venv)을 만들고 패키지를 설치합니다.
REM - 서버가 이미 켜져 있으면 브라우저만 엽니다.
REM - 서버는 작업 표시줄에 최소화된 창으로 돌아갑니다. 그 창을 닫으면 꺼집니다.
cd /d "%~dp0"
set BASEPY=D:\ananconda3\python.exe
set PORT=8501
set URL=http://localhost:%PORT%

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

netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul
if not errorlevel 1 goto open

echo 서버를 켜는 중입니다...
start "실거래가 서버 - 이 창을 닫으면 꺼집니다" /min ".venv\Scripts\python.exe" -m streamlit run app.py --server.headless true --server.port %PORT% --browser.gatherUsageStats false

set /a TRIES=0
:wait
timeout /t 1 /nobreak >nul
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul
if not errorlevel 1 goto open
set /a TRIES+=1
if %TRIES% lss 40 goto wait
echo [오류] 서버가 40초 안에 켜지지 않았습니다. 작업 표시줄의 "실거래가 서버" 창을 확인해 주세요.
pause
exit /b 1

:open
start "" "%URL%"
exit /b 0
