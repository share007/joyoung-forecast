#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
APP_NAME="JoyoungForecast-V1.0-Windows"
APP_DIR="$DIST_DIR/$APP_NAME"
PKG_ZIP="$DIST_DIR/${APP_NAME}.zip"

printf "\n[1/6] Building static frontend...\n"
cd "$ROOT_DIR/frontend"
npm ci
npm run build

printf "\n[2/6] Preparing dist directory...\n"
rm -rf "$APP_DIR" "$PKG_ZIP"
mkdir -p "$APP_DIR/app"

printf "\n[3/6] Copying backend code...\n"
rsync -a --delete \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'data/forecast.db' \
  "$ROOT_DIR/backend/" "$APP_DIR/app/backend/"

# Windows often fails to install LightGBM in user environments.
awk '!/^[[:space:]]*lightgbm==/' "$APP_DIR/app/backend/requirements.txt" > "$APP_DIR/app/backend/requirements-windows.txt"

printf "\n[4/6] Copying static frontend into backend/static_app...\n"
mkdir -p "$APP_DIR/app/backend/static_app"
rsync -a --delete "$ROOT_DIR/frontend/out/" "$APP_DIR/app/backend/static_app/"

cat > "$APP_DIR/start.bat" <<'EOF'
@echo off
setlocal enabledelayedexpansion

set "BASE_DIR=%~dp0"
set "APP_DIR=%BASE_DIR%app"
set "FORECAST_DB_PATH=%APP_DIR%\data\forecast.db"
cd /d "%APP_DIR%"

if not exist "%APP_DIR%\data" mkdir "%APP_DIR%\data"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY_CMD=py -3"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PY_CMD=python"
  ) else (
    echo [ERROR] Python 3 not found.
    echo Please install Python 3.9+ from https://www.python.org/downloads/
    pause
    exit /b 1
  )
)

if not exist ".venv\Scripts\python.exe" (
  %PY_CMD% -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul 2>nul
python -m pip install -r backend\requirements.txt
if %errorlevel% neq 0 (
  echo [WARN] Full dependency install failed. Retrying with Windows-compatible set...
  python -m pip install -r backend\requirements-windows.txt
  if %errorlevel% neq 0 (
    echo [ERROR] Dependency install failed. Please check network or app\app.log
    pause
    exit /b 1
  )
)

if exist app.pid (
  set /p OLD_PID=<app.pid
  tasklist /fi "PID eq !OLD_PID!" | findstr /i "!OLD_PID!" >nul 2>nul
  if !errorlevel!==0 (
    echo App is already running (PID=!OLD_PID!).
    start "" "http://127.0.0.1:8000/home/forecast/dashboard/"
    exit /b 0
  )
)

netstat -ano | findstr ":8000" >nul 2>nul
if %errorlevel%==0 (
  echo Port 8000 is already in use. Opening page directly.
  start "" "http://127.0.0.1:8000/home/forecast/dashboard/"
  exit /b 0
)

start "Joyoung Forecast" /b cmd /c "python backend\main.py > app.log 2>&1"
for /f "tokens=2" %%i in ('tasklist ^| findstr /i "python"') do (
  set "NEW_PID=%%i"
)
if defined NEW_PID (
  echo !NEW_PID!>app.pid
)

set /a RETRIES=30
:wait_api
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if !errorlevel!==0 goto api_ready
set /a RETRIES-=1
if !RETRIES! LEQ 0 goto api_timeout
timeout /t 1 >nul
goto wait_api

:api_ready
start "" "http://127.0.0.1:8000/home/forecast/dashboard/"
echo App started. Log file: %APP_DIR%\app.log
exit /b 0

:api_timeout
echo [ERROR] App did not become ready in time. Please check app\app.log
pause
exit /b 1
EOF

cat > "$APP_DIR/stop.bat" <<'EOF'
@echo off
setlocal

set "BASE_DIR=%~dp0"
set "APP_DIR=%BASE_DIR%app"
cd /d "%APP_DIR%"

if exist app.pid (
  set /p PID=<app.pid
  taskkill /PID %PID% /F >nul 2>nul
  if %errorlevel%==0 (
    echo App stopped (PID=%PID%).
  ) else (
    echo No running process found for PID=%PID%.
  )
  del /f /q app.pid >nul 2>nul
) else (
  echo app.pid not found.
)

exit /b 0
EOF

cat > "$APP_DIR/README-快速开始-Windows.txt" <<'EOF'
九阳预测系统 V1.0（Windows 一键版）

使用方式：
1. 双击 start.bat 启动应用
2. 浏览器会自动打开系统页面
3. 用完后双击 stop.bat 关闭应用

说明：
- 首次启动会自动安装依赖（需要联网）
- 需要 Windows 已安装 Python 3.9+
- 应用地址：http://127.0.0.1:8000/home/forecast/dashboard/
- 运行日志在 app\app.log
EOF

printf "\n[5/6] Creating zip package...\n"
cd "$DIST_DIR"
zip -rq "$PKG_ZIP" "$APP_NAME"

printf "\n[6/6] Done.\n"
echo "Package: $PKG_ZIP"
