$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Dist = Join-Path $Root 'dist'
$AppName = 'JoyoungForecast-V1.0-Windows-EXE'
$AppDir = Join-Path $Dist $AppName
$ZipPath = Join-Path $Dist "$AppName.zip"

Write-Host "`n[1/7] Build static frontend..."
Push-Location (Join-Path $Root 'frontend')
npm ci
npm run build
Pop-Location

Write-Host "`n[2/7] Prepare backend static assets..."
$StaticDir = Join-Path $Root 'backend/static_app'
if (Test-Path $StaticDir) { Remove-Item $StaticDir -Recurse -Force }
New-Item -ItemType Directory -Path $StaticDir | Out-Null
Copy-Item (Join-Path $Root 'frontend/out/*') $StaticDir -Recurse -Force

Write-Host "`n[3/7] Create build venv..."
$BuildVenv = Join-Path $Root '.venv-build-exe'
if (Test-Path $BuildVenv) { Remove-Item $BuildVenv -Recurse -Force }
py -3 -m venv $BuildVenv
$Py = Join-Path $BuildVenv 'Scripts/python.exe'
$Pip = Join-Path $BuildVenv 'Scripts/pip.exe'
& $Pip install --upgrade pip
& $Pip install -r (Join-Path $Root 'backend/requirements.txt')
& $Pip install pyinstaller

Write-Host "`n[4/7] Build Windows executable (onedir)..."
Push-Location $Root
& (Join-Path $BuildVenv 'Scripts/pyinstaller.exe') `
  --noconfirm `
  --clean `
  --name JoyoungForecastServer `
  --onedir `
  --add-data "backend/static_app;backend/static_app" `
  backend/main.py
Pop-Location

Write-Host "`n[5/7] Assemble distributable folder..."
if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $AppDir 'app') | Out-Null
New-Item -ItemType Directory -Path (Join-Path $AppDir 'app/data') | Out-Null
Copy-Item (Join-Path $Root 'dist/JoyoungForecastServer/*') (Join-Path $AppDir 'app/JoyoungForecastServer') -Recurse -Force

@'
@echo off
setlocal enabledelayedexpansion

set "BASE_DIR=%~dp0"
set "APP_DIR=%BASE_DIR%app"
set "FORECAST_DB_PATH=%APP_DIR%\data\forecast.db"

if not exist "%APP_DIR%\data" mkdir "%APP_DIR%\data"

if exist "%APP_DIR%\app.pid" (
  set /p OLD_PID=<"%APP_DIR%\app.pid"
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

cd /d "%APP_DIR%\JoyoungForecastServer"
start "Joyoung Forecast" /b cmd /c "JoyoungForecastServer.exe > ..\app.log 2>&1"
for /f "tokens=2" %%i in ('tasklist ^| findstr /i "JoyoungForecastServer.exe"') do (
  set "NEW_PID=%%i"
)
if defined NEW_PID (
  echo !NEW_PID!>"%APP_DIR%\app.pid"
)

timeout /t 2 >nul
start "" "http://127.0.0.1:8000/home/forecast/dashboard/"
echo App started. Log file: %APP_DIR%\app.log
exit /b 0
'@ | Set-Content -Encoding ASCII (Join-Path $AppDir 'start.bat')

@'
@echo off
setlocal

set "BASE_DIR=%~dp0"
set "APP_DIR=%BASE_DIR%app"

if exist "%APP_DIR%\app.pid" (
  set /p PID=<"%APP_DIR%\app.pid"
  taskkill /PID %PID% /F >nul 2>nul
  if %errorlevel%==0 (
    echo App stopped (PID=%PID%).
  ) else (
    echo No running process found for PID=%PID%.
  )
  del /f /q "%APP_DIR%\app.pid" >nul 2>nul
) else (
  echo app.pid not found.
)

exit /b 0
'@ | Set-Content -Encoding ASCII (Join-Path $AppDir 'stop.bat')

@'
Joyoung Forecast V1.0 (Windows EXE)

Usage:
1. Double-click start.bat
2. Browser opens automatically
3. Double-click stop.bat to stop

Notes:
- Python installation is NOT required
- App URL: http://127.0.0.1:8000/home/forecast/dashboard/
- Log file: app\app.log
'@ | Set-Content -Encoding UTF8 (Join-Path $AppDir 'README-Windows-EXE.txt')

Write-Host "`n[6/7] Create zip package..."
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path $AppDir -DestinationPath $ZipPath -Force

Write-Host "`n[7/7] Done"
Write-Host "Package: $ZipPath"
